"""Перебор способов записать субтитры.

CapCut не объясняет, почему не рисует текст. Сравнение черновика с шаблоном
показало, что все объекты субтитра совпадают, и тем не менее в кадре вместо
текста появляется заглушка текстового шаблона. Значит дело в чём-то, чего в
объектах субтитра не видно.

Поэтому здесь собирается один и тот же ролик несколько раз, каждый раз с другим
способом записи субтитров. Различается только дорожка субтитров: клипы, озвучка,
музыка, стикер и QR во всех роликах одни и те же. Достаточно открыть готовые
ролики и посмотреть, в каком тексте видно — так способ находится за один проход
вместо череды догадок.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import diagnose, meta, profile as profile_module, subtitles, validate
from .config import Config
from .draft_io import Draft
from .logging_setup import get_logger
from .plan import Cue
from .subtitles import Way

log = get_logger("variants")

# Порядок важен: сначала то, что ближе к нынешнему поведению.
WAYS: tuple[Way, ...] = (
    Way("A_как_сейчас", "как программа делает сейчас"),
    Way("B_ид_капкута", "опознаватели в виде, в каком их пишет CapCut, а не UUID",
        ids="capcut"),
    Way("C_ид_шаблона", "заняты те же опознаватели, что у субтитров шаблона",
        ids="template"),
    Way("D_простой_текст", "субтитр обычным текстом, без текстового шаблона",
        device="text"),
    Way("E_слова_шаблона", "разбиение по словам взято из шаблона без изменений",
        words="template"),
    Way("F_без_слов", "разбиение по словам пустое", words="empty"),
    Way("G_без_анимации", "без анимации подписи", animation=False),
    Way("H_размер_шаблона", "размер надписи как в шаблоне, а не по длине текста",
        size="template"),
)

CONTROL = "I_субтитры_шаблона"


@dataclass
class VariantOutcome:
    name: str
    note: str
    ok: bool
    folder: Path | None = None
    subtitle_count: int = 0
    error: str = ""


@dataclass
class VariantsReport:
    base: str = ""
    outcomes: list[VariantOutcome] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Собрано вариантов: {sum(1 for o in self.outcomes if o.ok)} "
            f"из {len(self.outcomes)} (основа: {self.base})",
            "",
            "Открой каждый в CapCut и посмотри, в каком видно текст субтитров:",
        ]
        for item in self.outcomes:
            mark = "+" if item.ok else "x"
            tail = f"реплик {item.subtitle_count}" if item.ok else item.error
            lines.append(f"  {mark} {item.name} — {item.note} ({tail})")
        lines += [
            "",
            "Назови те, где текст видно. Если ни в одном, скажи и это — тогда дело",
            "не в записи субтитров, а в самом проекте или в кэше CapCut.",
        ]
        return "\n".join(lines)


def build(config: Config, base_folder: Path, template_folder: Path,
          cues: list[Cue]) -> VariantsReport:
    """Делает копии готового ролика, различающиеся только субтитрами."""
    base_folder = Path(base_folder)
    template_folder = Path(template_folder)
    report = VariantsReport(base=base_folder.name)

    if not cues:
        raise ValueError("нет реплик, перебирать нечего")

    profile = profile_module.analyse(base_folder)
    log.info("Перебор способов записи субтитров: %d вариантов, реплик %d",
             len(WAYS) + 1, len(cues))

    # Опознаватели берём у шаблона, а не у готовой копии: в копии на дорожке
    # субтитров уже лежит то, что положила программа.
    template_profile = profile_module.analyse(template_folder)
    borrow = subtitles.original_ids(
        Draft.load(template_folder), template_profile.subtitles.track,
    ) if template_profile.subtitles else []

    for way in WAYS:
        report.outcomes.append(_make(config, base_folder, profile, cues, way, borrow))

    report.outcomes.append(_control(config, base_folder, template_folder))
    return report


def _make(config: Config, base_folder: Path, base_profile, cues: list[Cue],
          way: Way, borrow: list[dict]) -> VariantOutcome:
    outcome = VariantOutcome(name=way.name, note=way.note, ok=False)
    target = base_folder.parent / f"{base_folder.name}_{way.name}"

    try:
        _clone(base_folder, target)
        # Профиль берётся заново: дорожки в копии те же, но объекты свои.
        profile = profile_module.analyse(target)
        draft = Draft.load(target)
        # Занимаемое отдаём всегда: способ сам решает, брать опознаватели,
        # разбиение по словам или ничего.
        count = subtitles.apply(draft, profile, cues, way, borrow=borrow)
        draft.save()

        _register(config, base_folder, target)

        # Самопроверку здесь не делаем препятствием: часть способов нарочно
        # нарушает то, что она считает правильным — ради этого перебор и нужен.
        checked = validate.check(target)
        for item in [*checked.errors, *checked.warnings]:
            log.warning("   %s: %s", way.name, item)

        outcome.ok = True
        outcome.folder = target
        outcome.subtitle_count = count
        log.info("   %s: готово, реплик %d — %s", way.name, count, way.note)
    except Exception as exc:  # noqa: BLE001 - вариант не должен валить перебор
        outcome.error = str(exc)
        log.warning("   %s: не собрался — %s", way.name, exc)
    return outcome


def _control(config: Config, base_folder: Path, template_folder: Path) -> VariantOutcome:
    """Проверочный вариант: субтитры шаблона без изменений."""
    outcome = VariantOutcome(
        name=CONTROL,
        note="субтитры шаблона без изменений — проверка, что рисуется хоть что-то",
        ok=False,
    )
    target = base_folder.parent / f"{base_folder.name}_{CONTROL}"
    try:
        _clone(base_folder, target)
        count = diagnose.restore_template_subtitles(template_folder, target)
        _register(config, base_folder, target)
        outcome.ok = True
        outcome.folder = target
        outcome.subtitle_count = count
        log.info("   %s: готово, реплик %d", CONTROL, count)
    except Exception as exc:  # noqa: BLE001
        outcome.error = str(exc)
        log.warning("   %s: не собрался — %s", CONTROL, exc)
    return outcome


def _clone(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def _register(config: Config, base_folder: Path, target: Path) -> None:
    """Прописывает копию в списке проектов, иначе CapCut её не покажет.

    Медиа в копии уже на своих местах, поэтому подменять пути не нужно — меняются
    только опознаватель проекта, имя и длительность.
    """
    duration = int(Draft.load(target).content.get("duration") or 0)
    draft_id = meta.update_project_meta(target, target.name, duration, {})
    meta.register_in_index(
        config.drafts_dir, base_folder, target, draft_id, target.name, duration)
