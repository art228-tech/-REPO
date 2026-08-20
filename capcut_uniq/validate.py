"""Самопроверка собранного черновика.

Смысл в том, чтобы ловить ошибки до того, как проект откроют в CapCut: битая
ссылка на материал или наложение сегментов проявятся там как «повреждённый
проект» без объяснения причины.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .draft_io import Draft
from .logging_setup import get_logger
from .units import fmt

log = get_logger("validate")


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def describe(self) -> str:
        lines = [f"ошибок: {len(self.errors)}, предупреждений: {len(self.warnings)}"]
        lines += [f"  ОШИБКА: {item}" for item in self.errors]
        lines += [f"  внимание: {item}" for item in self.warnings]
        return "\n".join(lines)


def check(folder: Path) -> Report:
    report = Report()
    draft = Draft.load(folder)
    index = draft.material_index()
    total = draft.duration_us

    if total <= 0:
        report.errors.append("нулевая длительность проекта")

    for track_position, track in enumerate(draft.tracks):
        segments = track.get("segments") or []
        previous_end = -1
        for position, segment in enumerate(sorted(segments, key=lambda s: (s.get("target_timerange") or {}).get("start", 0))):
            where = f"дорожка {track_position} сегмент {position}"
            material_id = segment.get("material_id")
            if material_id and material_id not in index:
                report.errors.append(f"{where}: ссылка на несуществующий материал {material_id}")

            for ref in segment.get("extra_material_refs") or []:
                if ref not in index:
                    report.errors.append(f"{where}: висячая ссылка {ref}")

            timerange = segment.get("target_timerange") or {}
            start = int(timerange.get("start") or 0)
            duration = int(timerange.get("duration") or 0)
            if duration <= 0:
                report.errors.append(f"{where}: нулевая длительность")
            if start < 0:
                report.errors.append(f"{where}: отрицательное начало")
            if total and start + duration > total + 1000:
                report.warnings.append(
                    f"{where}: выходит за конец ролика ({fmt(start + duration)} > {fmt(total)})"
                )
            if start < previous_end:
                report.errors.append(
                    f"{where}: наезжает на предыдущий сегмент ({fmt(start)} < {fmt(previous_end)})"
                )
            previous_end = start + duration

    _check_media(draft, folder, report)
    _check_subtitles(draft, index, report)
    _check_subtitle_durations(draft, report)
    _check_keyframes(draft, report)

    log.debug("проверка %s: %s", folder.name, report.describe().splitlines()[0])
    return report


def _check_media(draft: Draft, folder: Path, report: Report) -> None:
    for section in ("videos", "audios"):
        for material in draft.materials.get(section) or []:
            path_value = material.get("path") or ""
            if not path_value:
                continue
            if "##_draftpath_placeholder_" in path_value:
                tail = path_value.split("_##", 1)[-1].lstrip("/")
                real = folder / tail
            else:
                real = Path(path_value)
                if not real.is_absolute():
                    real = folder / path_value
            if not real.exists():
                report.errors.append(
                    f"нет файла для материала {material.get('material_name') or material.get('name') or material.get('id')}: {real.name}"
                )


def _check_subtitles(draft: Draft, index: dict, report: Report) -> None:
    texts = {t["id"] for t in draft.materials.get("texts") or []}
    for template in draft.materials.get("text_templates") or []:
        for resource in template.get("text_info_resources") or []:
            text_id = resource.get("text_material_id")
            if text_id and text_id not in texts:
                report.errors.append(f"субтитр {template.get('id')} ссылается на пропавший текст {text_id}")
            for ref in resource.get("extra_material_refs") or []:
                if ref not in index:
                    report.errors.append(f"субтитр {template.get('id')}: висячая анимация {ref}")


def _check_subtitle_durations(draft: Draft, report: Report) -> None:
    """Слишком короткий субтитр на экране не появится."""
    texts = {t["id"] for t in draft.materials.get("texts") or []}
    templates = {t["id"] for t in draft.materials.get("text_templates") or []}
    for track in draft.tracks:
        if track.get("type") not in ("sticker", "text"):
            continue
        for position, segment in enumerate(track.get("segments") or []):
            material_id = segment.get("material_id")
            if material_id not in texts and material_id not in templates:
                continue
            duration = int((segment.get("target_timerange") or {}).get("duration") or 0)
            if duration < 150_000:
                report.errors.append(
                    f"субтитр {position} длится {duration / 1000:.0f} мс - его не будет видно"
                )


def _check_keyframes(draft: Draft, report: Report) -> None:
    """Кейфрейм положения обязан совпадать с трансформацией сегмента."""
    for track in draft.tracks:
        for segment in track.get("segments") or []:
            groups = segment.get("common_keyframes") or []
            if not groups:
                continue
            transform = (segment.get("clip") or {}).get("transform") or {}
            expected = {"KFTypePositionX": transform.get("x"), "KFTypePositionY": transform.get("y")}
            for group in groups:
                target = expected.get(group.get("property_type"))
                if target is None:
                    continue
                for keyframe in group.get("keyframe_list") or []:
                    values = keyframe.get("values") or []
                    if values and abs(float(values[0]) - float(target)) > 1e-6:
                        report.errors.append(
                            f"кейфрейм {group.get('property_type')} ({values[0]:.4f}) "
                            f"расходится с трансформацией ({float(target):.4f})"
                        )
                        break
