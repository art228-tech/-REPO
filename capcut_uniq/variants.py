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
from .draft_io import Draft, new_capcut_id
from .logging_setup import get_logger
from .plan import Cue
from .subtitles import Way

log = get_logger("variants")

# Имена короткие и отличаются с первой буквы: в списке проектов CapCut показывает
# начало имени и обрезает хвост, поэтому длинные имена с отличием в конце выглядят
# там одинаково.
WAYS: tuple[Way, ...] = (
    Way("A_сейчас", "как программа делает сейчас"),
    Way("B_идкапкута", "опознаватели в виде, в каком их пишет CapCut, а не UUID",
        ids="capcut"),
    Way("C_идшаблона", "заняты те же опознаватели, что у субтитров шаблона",
        ids="template"),
    Way("D_простой", "субтитр обычным текстом, без текстового шаблона",
        device="text"),
    Way("E_словашаблона", "разбиение по словам взято из шаблона без изменений",
        words="template"),
    Way("F_безслов", "разбиение по словам пустое", words="empty"),
    Way("G_безанимации", "без анимации подписи", animation=False),
    Way("H_размершаблона", "размер надписи как в шаблоне, а не по длине текста",
        size="template"),
)

CONTROL = "I_шаблон"

# Второй заход перебора: сужение между тем, что работает, и тем, что нет.
#
# Известно, что субтитры шаблона без изменений рисуются, а пересобранный
# текстовый шаблон с нашим текстом — нет. Значит виновато одно из изменений,
# которые программа вносит. Здесь берётся дорожка шаблона как есть и к ней
# добавляется по одному изменению: где текст в кадре пропадёт, то изменение и
# виновато.
STEPS: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("J_текст", "субтитры шаблона, заменён только текст",
     frozenset({"text"})),
    ("K_слова", "то же плюс наше разбиение по словам",
     frozenset({"text", "words"})),
    ("L_время", "то же плюс наши времена реплик",
     frozenset({"text", "words", "times"})),
    ("M_длина", "то же плюс наша длительность в оформлении",
     frozenset({"text", "words", "times", "attach"})),
    ("N_размер", "то же плюс наш размер надписи",
     frozenset({"text", "words", "times", "attach", "size"})),
    ("O_опознаватели", "то же плюс новые опознаватели — это уже как в A",
     frozenset({"text", "words", "times", "attach", "size", "ids"})),
)


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
    template: str = ""
    outcomes: list[VariantOutcome] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Собрано вариантов: {sum(1 for o in self.outcomes if o.ok)} "
            f"из {len(self.outcomes)}",
            f"Шаблон: {self.template}",
            f"Основа (её открывать не нужно): {self.base}",
            "",
            "В списке проектов CapCut ищи проекты с именами на A_ … O_",
            "Открой каждый и посмотри, в каком видно текст субтитров:",
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
    report.template = template_folder.name
    log.info("Перебор способов записи субтитров по шаблону %s: %d вариантов, реплик %d",
             template_folder.name, len(WAYS) + 1, len(cues))

    # Опознаватели берём у шаблона, а не у готовой копии: в копии на дорожке
    # субтитров уже лежит то, что положила программа.
    template_profile = profile_module.analyse(template_folder)
    borrow = subtitles.original_ids(
        Draft.load(template_folder), template_profile.subtitles.track,
    ) if template_profile.subtitles else []

    for way in WAYS:
        report.outcomes.append(_make(config, base_folder, profile, cues, way, borrow))

    report.outcomes.append(_control(config, base_folder, template_folder))

    for name, note, steps in STEPS:
        report.outcomes.append(
            _stepwise(config, base_folder, template_folder, cues, name, note, steps))

    _write_legend(base_folder.parent, report)
    return report


def _stepwise(config: Config, base_folder: Path, template_folder: Path,
              cues: list[Cue], name: str, note: str,
              steps: frozenset[str]) -> VariantOutcome:
    """Дорожка шаблона, к которой добавлено ровно перечисленное."""
    outcome = VariantOutcome(name=name, note=note, ok=False)
    target = base_folder.parent / name
    try:
        _clone(base_folder, target)
        diagnose.restore_template_subtitles(template_folder, target)

        draft = Draft.load(target)
        profile = profile_module.analyse(target)
        style = profile.subtitles
        if style is None:
            raise ValueError("дорожка субтитров не опознана")

        segments = draft.tracks[style.track].get("segments") or []
        texts = {m["id"]: m for m in draft.materials.get("texts") or []}
        templates = {m["id"]: m for m in draft.materials.get("text_templates") or []}
        animations = {m["id"]: m for m in draft.materials.get("material_animations") or []}

        # Сравнивать честно можно только столько реплик, сколько есть в обоих.
        count = min(len(segments), len(cues))
        del segments[count:]

        for position in range(count):
            _step_one(segments[position], cues[position], steps, style,
                      texts, templates, animations)

        draft.save()
        _register(config, base_folder, target)

        outcome.ok = True
        outcome.folder = target
        outcome.subtitle_count = count
        log.info("   %s: готово, реплик %d — %s", name, count, note)
    except Exception as exc:  # noqa: BLE001
        outcome.error = str(exc)
        log.warning("   %s: не собрался — %s", name, exc)
    return outcome


def _step_one(segment: dict, cue: Cue, steps: frozenset[str], style,
              texts: dict, templates: dict, animations: dict) -> None:
    """Вносит в один субтитр шаблона только перечисленные изменения."""
    template = templates.get(segment.get("material_id"))
    resources = (template.get("text_info_resources") or []) if template else []
    text_id = resources[0].get("text_material_id") if resources else segment.get("material_id")
    text = texts.get(text_id)

    if text is not None and "text" in steps:
        text["content"] = subtitles.rewrite_content(text.get("content") or "{}", cue.text)
        text["recognize_text"] = cue.text
    if text is not None and "words" in steps:
        text["words"] = subtitles.word_arrays(cue)

    if "times" in steps:
        segment["target_timerange"] = {"start": cue.start_us, "duration": cue.duration_us}

    for resource in resources:
        attach = resource.setdefault("attach_info", {})
        if "attach" in steps:
            attach["start_time"] = 0
            attach["duration"] = cue.duration_us
        if "size" in steps:
            width, height = subtitles.size_for(style.metrics, len(cue.text))
            attach["original_size_width"] = width
            attach["original_size_height"] = height

    for reference in segment.get("extra_material_refs") or []:
        animation = animations.get(reference)
        if animation and "attach" in steps:
            for item in animation.get("animations") or []:
                item["start"] = 0
                item["duration"] = cue.duration_us

    if "ids" in steps:
        _renumber(segment, template, text, animations)


def _renumber(segment: dict, template: dict | None, text: dict | None,
              animations: dict) -> None:
    """Выдаёт субтитру новые опознаватели, сохраняя связи между объектами."""
    if text is not None:
        text["id"] = new_capcut_id()
    if template is not None:
        template["id"] = new_capcut_id()
        segment["material_id"] = template["id"]
        for resource in template.get("text_info_resources") or []:
            if text is not None:
                resource["text_material_id"] = text["id"]
    elif text is not None:
        segment["material_id"] = text["id"]

    fresh: list[str] = []
    for reference in segment.get("extra_material_refs") or []:
        animation = animations.get(reference)
        if animation is None:
            fresh.append(reference)
            continue
        animation["id"] = new_capcut_id()
        fresh.append(animation["id"])
        if template is not None:
            for resource in template.get("text_info_resources") or []:
                resource["extra_material_refs"] = [animation["id"]]
    segment["extra_material_refs"] = fresh
    segment["id"] = new_capcut_id()


def _write_legend(folder: Path, report: VariantsReport) -> Path:
    """Памятка рядом с проектами: какая буква что означает."""
    path = folder / "перебор — что есть что.txt"
    lines = [
        f"Перебор способов записи субтитров по шаблону {report.template}.",
        f"Основа: {report.base} — её открывать не нужно.",
        "",
        "Девять проектов различаются только дорожкой субтитров.",
        "Клипы, озвучка, музыка, стикер и QR во всех одни и те же.",
        "",
    ]
    for item in report.outcomes:
        state = f"реплик {item.subtitle_count}" if item.ok else f"НЕ СОБРАЛСЯ: {item.error}"
        lines.append(f"{item.name}  —  {item.note}  ({state})")
    lines += [
        "",
        "Открой каждый и посмотри, видно ли текст субтитров.",
        "Назови те, где видно. Если ни в одном, включая I_шаблон, значит запись",
        "субтитров не при чём: CapCut не рисует этот текстовый шаблон в таком",
        "проекте, и искать надо в самом проекте или в кэше приложения.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Памятка: %s", path)
    return path


def _make(config: Config, base_folder: Path, base_profile, cues: list[Cue],
          way: Way, borrow: list[dict]) -> VariantOutcome:
    outcome = VariantOutcome(name=way.name, note=way.note, ok=False)
    target = base_folder.parent / way.name

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
    target = base_folder.parent / CONTROL
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
