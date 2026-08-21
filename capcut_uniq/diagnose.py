"""Диагностика субтитров: сравнение собранного ролика с шаблоном.

Смысл модуля простой. Субтитр может лежать в черновике совершенно правильно с
точки зрения ссылок и таймингов, пройти самопроверку — и всё равно не появиться
на экране, потому что какое-то поле отличается от того, что кладёт сам CapCut.
Увидеть это по скриншоту невозможно: текст в превью размером в несколько
пикселей.

Поэтому здесь снимается полный слепок субтитров из шаблона и из собранного
ролика, поля сравниваются между собой, и проверяются инварианты, которые
выполняются во всех рабочих проектах. Результат складывается в один небольшой
файл, который можно переслать.
"""
from __future__ import annotations

import copy
import json
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import profile as profile_module
from .draft_io import Draft
from .logging_setup import get_logger

log = get_logger("diagnose")

# Поля, которые обязаны отличаться: идентификаторы, текст и тайминги.
EXPECTED_DIFFERENT = {
    "id", "name", "content", "words", "current_words", "recognize_text",
    "group_id", "material_id", "target_timerange", "extra_material_refs",
    "render_index", "text_info_resources", "recognize_task_id",
}


@dataclass
class Finding:
    level: str
    text: str


@dataclass
class SubtitleReport:
    template: str
    clone: str
    findings: list[Finding] = field(default_factory=list)
    payload: dict = field(default_factory=dict)

    def add(self, level: str, text: str) -> None:
        self.findings.append(Finding(level, text))

    @property
    def problems(self) -> list[Finding]:
        return [item for item in self.findings if item.level != "ок"]

    def describe(self) -> str:
        lines = [f"Диагностика субтитров: шаблон {self.template} → ролик {self.clone}"]
        for item in self.findings:
            mark = {"ок": "  +", "внимание": "  !", "ошибка": "  x"}.get(item.level, "  ?")
            lines.append(f"{mark} {item.text}")
        return "\n".join(lines)


def _chain(draft: Draft, style) -> list[dict]:
    """Собирает цепочку объектов каждого субтитра дорожки.

    Возвращает по одной записи на сегмент: сам сегмент, текстовый шаблон (если
    он есть), текст и анимацию — то есть всё, что участвует в отрисовке.
    """
    index = draft.material_index()
    texts = {t["id"]: t for t in draft.materials.get("texts") or []}
    animations = {a["id"]: a for a in draft.materials.get("material_animations") or []}

    chain: list[dict] = []
    for segment in draft.tracks[style.track].get("segments") or []:
        entry: dict = {"segment": segment}
        material_id = segment.get("material_id")
        found = index.get(material_id)

        if found and found[0] == "text_templates":
            template = found[1]
            entry["text_template"] = template
            resources = template.get("text_info_resources") or []
            if resources:
                entry["resource"] = resources[0]
                entry["text"] = texts.get(resources[0].get("text_material_id"))
                refs = resources[0].get("extra_material_refs") or []
                if refs:
                    entry["animation"] = animations.get(refs[0])
        else:
            entry["text"] = texts.get(material_id)
            for ref in segment.get("extra_material_refs") or []:
                if ref in animations:
                    entry["animation"] = animations[ref]
                    break
        chain.append(entry)
    return chain


def _visible_text(text_material: dict | None) -> str:
    if not text_material:
        return ""
    try:
        return json.loads(text_material.get("content") or "{}").get("text") or ""
    except ValueError:
        return ""


def _без_таймингов(value):
    """Убирает из объекта то, что обязано отличаться: длительности и позиции.

    Длительность анимации подписи всегда равна длительности реплики, а реплики у
    ролика свои. Сравнивать надо всё остальное.
    """
    if isinstance(value, dict):
        return {
            key: _без_таймингов(item)
            for key, item in value.items()
            if key not in ("duration", "start", "start_time", "end_time")
        }
    if isinstance(value, list):
        return [_без_таймингов(item) for item in value]
    return value


def _diff_fields(left: dict | None, right: dict | None, label: str, report: SubtitleReport) -> None:
    """Сравнивает объекты и жалуется на неожиданные расхождения."""
    if not left or not right:
        report.add("ошибка", f"{label}: объект отсутствует "
                             f"(в шаблоне {'есть' if left else 'нет'}, "
                             f"в ролике {'есть' if right else 'нет'})")
        return

    only_left = sorted(set(left) - set(right))
    only_right = sorted(set(right) - set(left))
    if only_left:
        report.add("ошибка", f"{label}: в ролике пропали поля {only_left}")
    if only_right:
        report.add("внимание", f"{label}: в ролике появились поля {only_right}")

    unexpected = []
    for key in sorted(set(left) & set(right)):
        if key in EXPECTED_DIFFERENT:
            continue
        if _без_таймингов(left[key]) != _без_таймингов(right[key]):
            unexpected.append(key)
    if unexpected:
        for key in unexpected:
            report.add(
                "ошибка",
                f"{label}: поле {key} отличается — в шаблоне "
                f"{json.dumps(left[key], ensure_ascii=False)[:120]}, в ролике "
                f"{json.dumps(right[key], ensure_ascii=False)[:120]}",
            )
    else:
        report.add("ок", f"{label}: все поля кроме текста и таймингов совпадают с шаблоном")


def _check_invariants(chain: list[dict], report: SubtitleReport, where: str) -> None:
    """Проверяет то, что выполняется во всех рабочих проектах."""
    if not chain:
        report.add("ошибка", f"{where}: на дорожке нет ни одного субтитра")
        return

    previous_end = -1
    for position, entry in enumerate(chain):
        segment = entry["segment"]
        timerange = segment.get("target_timerange") or {}
        start = int(timerange.get("start") or 0)
        duration = int(timerange.get("duration") or 0)
        text = _visible_text(entry.get("text"))
        name = f"{where}, субтитр {position}"

        if duration <= 0:
            report.add("ошибка", f"{name}: нулевая длительность")
        elif duration < 150_000:
            report.add("ошибка", f"{name}: длится {duration // 1000} мс, на экране не появится")

        if start < previous_end:
            report.add("ошибка", f"{name}: начинается раньше, чем кончился предыдущий")
        previous_end = start + duration

        if not text:
            report.add("ошибка", f"{name}: пустой текст")

        # Диапазон оформления считается в символах.
        try:
            body = json.loads((entry.get("text") or {}).get("content") or "{}")
        except ValueError:
            body = {}
        for style in body.get("styles") or []:
            span = style.get("range") or []
            if len(span) == 2 and span[1] != len(text):
                report.add(
                    "ошибка",
                    f"{name}: диапазон оформления {span}, а в тексте {len(text)} символов",
                )

        # Ключевой инвариант: последнее слово кончается на краю реплики.
        words = (entry.get("text") or {}).get("words") or {}
        ends = words.get("end_time") or []
        starts = words.get("start_time") or []
        if ends:
            expected = duration // 1000
            if abs(max(ends) - expected) > 2:
                report.add(
                    "ошибка",
                    f"{name}: слова кончаются на {max(ends)} мс, а реплика длится {expected} мс",
                )
            if starts != sorted(starts):
                report.add("ошибка", f"{name}: времена слов идут не по возрастанию")
            if len(starts) != len(ends) or len(starts) != len(words.get("text") or []):
                report.add("ошибка", f"{name}: массивы слов разной длины")
        else:
            report.add("внимание", f"{name}: у текста нет разбиения по словам")

        # Длительность анимации подписи должна совпадать с репликой.
        animation = entry.get("animation")
        if animation:
            for item in animation.get("animations") or []:
                if abs(int(item.get("duration") or 0) - duration) > 2000:
                    report.add(
                        "ошибка",
                        f"{name}: анимация «{item.get('type')}» длится "
                        f"{int(item.get('duration') or 0) // 1000} мс вместо {duration // 1000}",
                    )
        else:
            report.add("внимание", f"{name}: анимация подписи не найдена")

        resource = entry.get("resource")
        if resource:
            attach = resource.get("attach_info") or {}
            if abs(int(attach.get("duration") or 0) - duration) > 2000:
                report.add(
                    "ошибка",
                    f"{name}: в оформлении записана длительность "
                    f"{int(attach.get('duration') or 0) // 1000} мс вместо {duration // 1000}",
                )


def _check_fonts(chain: list[dict], report: SubtitleReport) -> None:
    """Проверяет, лежат ли на диске шрифты, на которые ссылается текст."""
    missing: set[str] = set()
    android: set[str] = set()
    for entry in chain:
        text = entry.get("text") or {}
        paths = [text.get("font_path") or ""]
        for font in text.get("fonts") or []:
            paths.append(font.get("path") or "")
        for item in paths:
            if not item:
                continue
            if item.startswith("/data/"):
                android.add(item)
            elif not Path(item).exists():
                missing.add(item)

    if missing:
        report.add("ошибка", f"файлы шрифтов не найдены на диске: {sorted(missing)[:3]}")
    elif android:
        # Ровно так же записано в шаблоне: CapCut находит шрифт по своему
        # идентификатору, а не по этому пути. Поломкой это не является.
        report.add("ок", f"шрифты указаны путями от телефона ({len(android)} шт), как в шаблоне")
    else:
        report.add("ок", "все шрифты на месте")


def _check_content_fidelity(template_chain: list[dict], clone_chain: list[dict],
                            report: SubtitleReport) -> None:
    """Сверяет оформление субтитра побайтово, а не по смыслу.

    Оформление лежит в черновике как JSON внутри строки, и одно и то же по смыслу
    содержимое можно записать разными байтами: с пробелами после запятых или без,
    с полной записью дробного числа или сокращённой. Обычное сравнение объектов
    такую разницу не видит, поэтому здесь берётся оформление из шаблона, в него
    подставляется текст ролика, и результат сравнивается со тем, что в ролике
    действительно лежит.
    """
    from .subtitles import rewrite_content

    if not template_chain or not clone_chain:
        return

    origin = (template_chain[0].get("text") or {}).get("content") or ""
    if not origin:
        return

    bad = 0
    example = ""
    for entry in clone_chain:
        actual = (entry.get("text") or {}).get("content") or ""
        try:
            text = json.loads(actual).get("text") or ""
        except ValueError:
            continue
        wanted = rewrite_content(origin, text)
        if actual != wanted:
            bad += 1
            if not example:
                position = next(
                    (i for i, (a, b) in enumerate(zip(actual, wanted)) if a != b),
                    min(len(actual), len(wanted)),
                )
                low = max(0, position - 30)
                example = (f"с позиции {position}: в ролике …{actual[low:position + 30]}… "
                           f"а надо …{wanted[low:position + 30]}…")

    if bad:
        report.add("ошибка", f"оформление записано не теми байтами, что в шаблоне "
                            f"({bad} из {len(clone_chain)}) — {example}")
    else:
        report.add("ок", "оформление записано теми же байтами, что в шаблоне")


def compare(template_folder: Path, clone_folder: Path) -> SubtitleReport:
    """Сравнивает субтитры собранного ролика с субтитрами шаблона."""
    template_folder = Path(template_folder)
    clone_folder = Path(clone_folder)
    report = SubtitleReport(template=template_folder.name, clone=clone_folder.name)

    template_profile = profile_module.analyse(template_folder)
    clone_profile = profile_module.analyse(clone_folder)

    if template_profile.subtitles is None:
        report.add("ошибка", "в шаблоне не опознана дорожка субтитров")
        return report
    if clone_profile.subtitles is None:
        report.add("ошибка", "в собранном ролике не опознана дорожка субтитров")
        return report

    # Разное устройство — не поломка: обычный текстовый материал выбран нарочно,
    # потому что через текстовый шаблон CapCut наш текст в кадре не рисует.
    same_device = template_profile.subtitles.kind == clone_profile.subtitles.kind
    if not same_device:
        report.add(
            "ок",
            f"устройство субтитров разное по замыслу: в шаблоне "
            f"{template_profile.subtitles.kind}, в ролике {clone_profile.subtitles.kind}",
        )

    template_chain = _chain(Draft.load(template_folder), template_profile.subtitles)
    clone_chain = _chain(Draft.load(clone_folder), clone_profile.subtitles)

    report.add("ок", f"субтитров: в шаблоне {len(template_chain)}, в ролике {len(clone_chain)}")

    _check_invariants(clone_chain, report, "ролик")
    _check_fonts(clone_chain, report)
    _check_content_fidelity(template_chain, clone_chain, report)

    if template_chain and clone_chain:
        _diff_fields(template_chain[0].get("text"), clone_chain[0].get("text"), "текст", report)
        if same_device:
            _diff_fields(template_chain[0].get("text_template"),
                         clone_chain[0].get("text_template"), "оформление", report)
        _diff_fields(template_chain[0].get("segment"), clone_chain[0].get("segment"),
                     "сегмент", report)
        _diff_fields(template_chain[0].get("animation"), clone_chain[0].get("animation"),
                     "анимация", report)

    report.payload = {
        "снято": datetime.now().isoformat(timespec="seconds"),
        "система": f"{platform.system()} {platform.release()}",
        "python": sys.version.split()[0],
        "шаблон": {
            "имя": template_folder.name,
            "дорожка": template_profile.subtitles.track,
            "устройство": template_profile.subtitles.kind,
            "субтитры": [_slim(entry) for entry in template_chain],
        },
        "ролик": {
            "имя": clone_folder.name,
            "длительность": clone_profile.total_us,
            "кадров": clone_profile.fps,
            "дорожка": clone_profile.subtitles.track,
            "устройство": clone_profile.subtitles.kind,
            "субтитры": [_slim(entry) for entry in clone_chain],
        },
        "находки": [{"уровень": f.level, "текст": f.text} for f in report.findings],
    }
    return report


def _slim(entry: dict) -> dict:
    """Слепок одного субтитра целиком, но без лишнего объёма."""
    return {
        "сегмент": entry.get("segment"),
        "оформление": entry.get("text_template"),
        "текст": entry.get("text"),
        "анимация": entry.get("animation"),
    }


def restore_template_subtitles(template_folder: Path, clone_folder: Path) -> int:
    """Кладёт в собранный ролик субтитры шаблона без изменений.

    Это проба на разделение причин. Всё в ролике остаётся своим — клипы,
    озвучка, музыка, стикер, — а дорожка субтитров становится буквально той же,
    что в шаблоне: тот же текст, те же времена, те же байты.

    Если после этого субтитры видно, значит дело в том, что программа собирает,
    и разбираться надо в сборке. Если по-прежнему не видно, значит собранные
    субтитры тут вообще не при чём: CapCut не рисует этот текстовый шаблон в
    таком проекте, и искать надо в самом проекте или в кэше приложения.
    """
    template_folder = Path(template_folder)
    clone_folder = Path(clone_folder)

    template_profile = profile_module.analyse(template_folder)
    clone_profile = profile_module.analyse(clone_folder)
    if template_profile.subtitles is None or clone_profile.subtitles is None:
        raise ValueError("дорожка субтитров не опознана")

    source = Draft.load(template_folder)
    target = Draft.load(clone_folder)

    kinds = ("text_templates", "texts", "material_animations")
    source_pool = {kind: {m["id"]: m for m in source.materials.get(kind) or []}
                   for kind in kinds}

    # Убираем то, что положила программа, чтобы не осталось висячих материалов.
    doomed = _referenced(target, clone_profile.subtitles.track)
    for kind in kinds:
        target.materials[kind] = [
            m for m in target.materials.get(kind) or [] if m["id"] not in doomed
        ]

    segments = copy.deepcopy(source.tracks[template_profile.subtitles.track]
                             .get("segments") or [])
    wanted = _referenced(source, template_profile.subtitles.track)
    for kind in kinds:
        target.materials.setdefault(kind, []).extend(
            copy.deepcopy(source_pool[kind][item])
            for item in wanted if item in source_pool[kind]
        )

    target.tracks[clone_profile.subtitles.track]["segments"] = segments

    backup = clone_folder / "draft_content.json.до_пробы"
    if not backup.exists():
        backup.write_text((clone_folder / "draft_content.json").read_text(encoding="utf-8"),
                          encoding="utf-8")
    target.save()
    log.info("В ролик %s положены субтитры шаблона: %d реплик (запас в %s)",
             clone_folder.name, len(segments), backup.name)
    return len(segments)


def _referenced(draft: Draft, track: int) -> set[str]:
    """Все материалы, на которые опирается дорожка."""
    index = draft.material_index()
    found: set[str] = set()

    for segment in draft.tracks[track].get("segments") or []:
        for item in [segment.get("material_id"), *(segment.get("extra_material_refs") or [])]:
            if not item:
                continue
            found.add(item)
            entry = index.get(item)
            if entry and entry[0] == "text_templates":
                for resource in entry[1].get("text_info_resources") or []:
                    found.add(resource.get("text_material_id"))
                    found.update(resource.get("extra_material_refs") or [])
    return {item for item in found if item}


def write_bundle(report: SubtitleReport, folder: Path) -> Path:
    """Складывает слепок в файл, который можно переслать для разбора."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"диагностика_{report.clone}.json"
    path.write_text(
        json.dumps(report.payload, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    log.info("Слепок для разбора: %s", path)
    return path
