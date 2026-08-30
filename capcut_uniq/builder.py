"""Сборка одного ролика: клон шаблона плюс подстановка нового содержимого.

Принцип — ничего не изобретать. Мы не создаём объекты CapCut с нуля, а копируем
папку рабочего проекта и правим в ней только то, что должно измениться: пути к
медиа, тайминги, масштабы, громкости и текст субтитров. Всё остальное —
эффекты, анимации, хромакей, оформление подписей — наследуется как есть.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import meta, subtitles
from .config import Config
from .draft_io import Draft, clone_folder, new_capcut_id
from .ffmpeg import MediaInfo, probe
from .logging_setup import get_logger
from .plan import RenderPlan
from .profile import SegRef, TemplateProfile
from .units import fmt, us2s

log = get_logger("builder")


@dataclass
class BuildResult:
    folder: Path
    name: str
    draft_id: str
    duration_us: int
    subtitle_count: int
    notes: list[str] = field(default_factory=list)
    font_name: str = ""
    """Имя файла подставленного шрифта — по нему видно, разные ли они в партии."""
    font_own: bool = True
    """Свой шрифт шаблона, а не общий запасной."""


def build(profile: TemplateProfile, plan: RenderPlan, config: Config, name: str) -> BuildResult:
    target = config.drafts_dir / name
    notes = list(plan.notes)

    replaced_media = _materials_to_replace(profile)
    skip = [path for path in replaced_media.values() if path and path.exists()]
    log.debug("клонирую %s → %s, пропускаю %d медиафайла", profile.folder.name, name, len(skip))
    clone_folder(profile.folder, target, skip_files=skip)

    draft = Draft.load(target)
    # Идентификатор таймлайна оставляем как в шаблоне. Раньше здесь выдавался
    # новый, и если рядом оставался хоть один служебный файл со старым, CapCut
    # видел два таймлайна и открывал пустой. Проекты лежат в разных папках, так
    # что совпадение идентификатора внутри них ничему не мешает.
    draft.content["name"] = name
    draft.duration_us = plan.total_us
    draft.content["fps"] = float(config.fps)

    media_map = _install_media(draft, profile, plan, target)
    _apply_slots(draft, profile, plan, media_map, notes)
    _apply_voice(draft, profile, plan, media_map)
    _apply_sfx(draft, plan.swoosh)
    _apply_decor(draft, plan.sticker, is_sticker=True)
    _apply_decor(draft, plan.qr, is_sticker=False)
    _apply_sfx(draft, plan.sticker.sfx if plan.sticker else None)
    _apply_sfx(draft, plan.qr.sfx if plan.qr else None)
    _apply_music(draft, profile, plan)

    subtitle_count = 0
    font = subtitles.fonts.Choice(source="записанный")
    if config.make_subtitles and plan.cues:
        way = subtitles.Way(
            device="text" if config.subtitle_device == "простой" else "auto")
        font = subtitles.choose_font(draft, profile, way)
        if font.source != "записанный":
            (log.info if font.own else log.warning)("   %s", font.describe())
        subtitle_count = subtitles.apply(draft, profile, plan.cues, way,
                                         font_path=font.path)
    elif not config.make_subtitles:
        removed = subtitles.clear(draft, profile)
        if removed:
            notes.append(f"дорожка субтитров очищена ({removed} реплик из шаблона)")

    draft.save()

    draft_id = meta.update_project_meta(
        target, name, plan.total_us, _meta_replacements(profile, plan, media_map)
    )
    meta.register_in_index(config.drafts_dir, profile.folder, target, draft_id, name, plan.total_us)

    return BuildResult(
        folder=target,
        name=name,
        draft_id=draft_id,
        duration_us=plan.total_us,
        subtitle_count=subtitle_count,
        notes=notes,
        font_name=Path(font.path).name if font.path else "",
        font_own=font.own,
    )


# --- медиа -------------------------------------------------------------------


def _resolve(folder: Path, path_value: str) -> Path | None:
    """Превращает ссылку из черновика в реальный путь внутри папки проекта."""
    if not path_value:
        return None
    if "##_draftpath_placeholder_" in path_value:
        tail = path_value.split("_##", 1)[-1].lstrip("/")
        return folder / tail
    candidate = Path(path_value)
    return candidate if candidate.is_absolute() else folder / path_value


def _materials_to_replace(profile: TemplateProfile) -> dict[str, Path | None]:
    """Идентификатор материала → файл в шаблоне, который заменяется."""
    draft = Draft.load(profile.folder)
    index = draft.material_index()
    result: dict[str, Path | None] = {}
    for material_id in [*profile.gameplay_material_ids, profile.voice_material_id]:
        entry = index.get(material_id)
        if entry:
            result[material_id] = _resolve(profile.folder, entry[1].get("path") or "")
    return result


@dataclass
class InstalledMedia:
    material_ids: list[str]
    filename: str
    relative: str
    info: MediaInfo
    old_relative: str = ""


def _install_media(draft: Draft, profile: TemplateProfile, plan: RenderPlan, target: Path) -> dict[str, InstalledMedia]:
    """Кладёт новые файлы в проект и обновляет описания материалов."""
    index = draft.material_index()
    installed: dict[str, InstalledMedia] = {}

    slot_materials: list[list[str]] = [[], []]
    for position, slot in enumerate(profile.slots):
        for ref in (slot.background, slot.overlay):
            material_id = ref.get(draft).get("material_id")
            if material_id and material_id not in slot_materials[position]:
                slot_materials[position].append(material_id)

    for position, clip in enumerate(plan.clips):
        info = probe(clip)
        filename = f"{new_capcut_id()}{clip.suffix.lower()}"
        destination = target / "video" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(clip, destination)
        relative = draft.relative_media_path("video", filename)

        old_relative = ""
        for material_id in slot_materials[position]:
            entry = index.get(material_id)
            if not entry:
                continue
            material = entry[1]
            old_relative = old_relative or _short_relative(material.get("path") or "")
            material["path"] = relative
            material["material_name"] = clip.name
            material["duration"] = int(info.duration_s * 1_000_000)
            material["width"] = info.width or material.get("width")
            material["height"] = info.height or material.get("height")
            material["has_audio"] = bool(info.has_audio)

        installed[f"slot{position}"] = InstalledMedia(
            material_ids=slot_materials[position],
            filename=filename,
            relative=relative,
            info=info,
            old_relative=old_relative,
        )

    voice_info = probe(plan.voice_path)
    voice_name = f"{new_capcut_id()}{plan.voice_path.suffix.lower()}"
    voice_destination = target / "audio" / voice_name
    voice_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(plan.voice_path, voice_destination)
    voice_relative = draft.relative_media_path("audio", voice_name)

    voice_material = index.get(profile.voice_material_id)
    old_voice_relative = ""
    if voice_material:
        material = voice_material[1]
        old_voice_relative = _short_relative(material.get("path") or "")
        material["path"] = voice_relative
        material["name"] = plan.voice_path.name
        material["duration"] = int(voice_info.duration_s * 1_000_000)

    installed["voice"] = InstalledMedia(
        material_ids=[profile.voice_material_id],
        filename=voice_name,
        relative=voice_relative,
        info=voice_info,
        old_relative=old_voice_relative,
    )
    return installed


def _short_relative(path_value: str) -> str:
    """Путь в том виде, в каком он записан в метаданных: ./audio/xxx.mp3."""
    if "##_draftpath_placeholder_" in path_value:
        return "." + path_value.split("_##", 1)[-1]
    return path_value


def _meta_replacements(profile: TemplateProfile, plan: RenderPlan, media: dict[str, InstalledMedia]):
    voice = media.get("voice")
    if not voice or not voice.old_relative:
        return {}
    return {
        voice.old_relative: (
            f"./audio/{voice.filename}",
            plan.voice_path.name,
            int(voice.info.duration_s * 1_000_000),
        )
    }


# --- сегменты ----------------------------------------------------------------


def _set_range(segment: dict, key: str, start: int, duration: int) -> None:
    segment[key] = {"start": int(start), "duration": int(duration)}


def _fit_height(width: int, height: int, canvas_w: int, canvas_h: int) -> float:
    if width <= 0 or height <= 0:
        return 0.0
    return height * min(canvas_w / width, canvas_h / height)


def _compensated(scale: float, old: MediaInfo | None, new: MediaInfo,
                 canvas_w: int, canvas_h: int) -> tuple[float, bool]:
    """Подгоняет масштаб, если у нового клипа другое соотношение сторон.

    Масштаб в CapCut отсчитывается от размера, вписанного в холст. Клип с другим
    соотношением вписывается иначе, и без поправки кадрирование уехало бы.
    """
    if old is None or old.width <= 0 or new.width <= 0:
        return scale, False
    old_fit = _fit_height(old.width, old.height, canvas_w, canvas_h)
    new_fit = _fit_height(new.width, new.height, canvas_w, canvas_h)
    if old_fit <= 0 or new_fit <= 0 or abs(old_fit - new_fit) / old_fit < 0.01:
        return scale, False
    return scale * old_fit / new_fit, True


def _apply_slots(draft: Draft, profile: TemplateProfile, plan: RenderPlan,
                 media: dict[str, InstalledMedia], notes: list[str]) -> None:
    canvas = draft.content.get("canvas_config") or {}
    canvas_w = int(canvas.get("width") or 1080)
    canvas_h = int(canvas.get("height") or 1920)

    template_sizes = _template_slot_sizes(profile)
    start = 0
    for position, slot in enumerate(profile.slots):
        duration = plan.slot_durations[position]
        speed = plan.slot_speeds[position] if plan.slot_speeds else 1.0
        source_duration = int(round(duration * speed))
        installed = media[f"slot{position}"]

        for ref, base_scale, is_overlay in (
            (slot.background, slot.background_scale, False),
            (slot.overlay, plan.overlay_scales[position], True),
        ):
            segment = ref.get(draft)
            _set_range(segment, "target_timerange", start, duration)
            _set_range(segment, "source_timerange", 0, source_duration)
            segment["speed"] = speed
            for material in _refs(draft, segment, "speeds"):
                material["speed"] = speed

            scale, changed = _compensated(
                base_scale, template_sizes.get(position), installed.info, canvas_w, canvas_h
            )
            clip = segment.setdefault("clip", {})
            clip.setdefault("scale", {})["x"] = scale
            clip["scale"]["y"] = scale

            # Фон гасим прозрачностью, а не удалением: сегмент остаётся на месте
            # со своим звуком и размытием, просто в кадре его не видно и сквозь
            # него виден чёрный холст.
            if plan.black_background and not is_overlay:
                clip["alpha"] = 0.0
                _drop_alpha_keyframes(segment)

            if plan.frame_shift:
                _shift_frame(clip, scale, plan.frame_shift, position, is_overlay, notes)
            if changed and not is_overlay:
                notes.append(
                    f"слот {position + 1}: у клипа другое соотношение сторон, "
                    f"масштаб пересчитан {base_scale:.3f} → {scale:.3f}"
                )
        start += duration


def _shift_frame(clip: dict, scale: float, share: float, position: int,
                 is_overlay: bool, notes: list[str]) -> None:
    """Двигает рамку вбок, показывая другую часть клипа.

    Клип шире кадра — при масштабе больше единицы его бока обрезаны, и там
    остаётся неиспользованная картинка. Сдвиг открывает её: часть прежнего кадра
    уходит, столько же приходит с обрезанной стороны.

    Сдвиг задан долей ширины кадра, а в черновике он записан в долях половины
    ширины, отсюда удвоение. Дальше некуда — за краем клипа пойдёт пустота,
    поэтому сдвиг обрезается по тому, сколько картинки в запасе.
    """
    transform = clip.setdefault("transform", {})
    current = float(transform.get("x") or 0.0)

    room = max(0.0, scale - 1.0)
    wanted = current + share * 2.0
    limit = max(-room, min(room, wanted))

    transform["x"] = limit
    if abs(limit - wanted) > 1e-6 and not is_overlay:
        notes.append(
            f"слот {position + 1}: кадр сдвинут на {abs(limit) / 2:.0%} вместо "
            f"{abs(share):.0%} — дальше у клипа нет запаса по краям"
        )


def _drop_alpha_keyframes(segment: dict) -> None:
    """Убирает ключевые кадры прозрачности — иначе они перебьют погашенный фон."""
    for group in segment.get("common_keyframes") or []:
        items = group.get("keyframe_list") or []
        group["keyframe_list"] = [
            item for item in items if "alpha" not in str(item.get("property_type", "")).lower()
        ]
    segment["common_keyframes"] = [
        group for group in segment.get("common_keyframes") or []
        if group.get("keyframe_list")
    ]


def _template_slot_sizes(profile: TemplateProfile) -> dict[int, MediaInfo]:
    """Размеры исходных клипов шаблона — нужны для поправки масштаба."""
    draft = Draft.load(profile.folder)
    index = draft.material_index()
    sizes: dict[int, MediaInfo] = {}
    for position, slot in enumerate(profile.slots):
        material_id = slot.background.get(draft).get("material_id")
        entry = index.get(material_id)
        if not entry:
            continue
        material = entry[1]
        sizes[position] = MediaInfo(
            path=Path(material.get("path") or ""),
            duration_s=float(material.get("duration") or 0) / 1_000_000,
            width=int(material.get("width") or 0),
            height=int(material.get("height") or 0),
        )
    return sizes


def _apply_voice(draft: Draft, profile: TemplateProfile, plan: RenderPlan,
                 media: dict[str, InstalledMedia]) -> None:
    segment = profile.voice.get(draft)
    _set_range(segment, "target_timerange", plan.voice_start_us, plan.voice_duration_us)
    _set_range(segment, "source_timerange", 0, plan.voice_duration_us)


def _apply_sfx(draft: Draft, placement) -> None:
    """Двигает звуковой акцент. Громкость трогаем, только если её задал план."""
    if placement is None:
        return
    segment = placement.ref.get(draft)
    _set_range(segment, "target_timerange", placement.start_us, placement.duration_us)
    source = segment.get("source_timerange") or {}
    _set_range(segment, "source_timerange", int(source.get("start") or 0), placement.duration_us)
    if placement.volume is not None:
        segment["volume"] = placement.volume


def _apply_decor(draft: Draft, placement, is_sticker: bool) -> None:
    if placement is None:
        return

    segment = placement.ref.get(draft)
    _set_range(segment, "target_timerange", placement.start_us, placement.duration_us)

    if is_sticker:
        _set_range(segment, "source_timerange", 0, placement.source_duration_us)
        segment["speed"] = placement.speed
        for material in _refs(draft, segment, "speeds"):
            material["speed"] = placement.speed
    else:
        _set_range(segment, "source_timerange", 0, placement.duration_us)

    clip = segment.setdefault("clip", {})
    transform = clip.setdefault("transform", {})
    transform["y"] = placement.offset_y

    # Длительность комбо-анимации обязана совпадать с длительностью сегмента,
    # иначе она оборвётся или растянется.
    for material in _refs(draft, segment, "material_animations"):
        for animation in material.get("animations") or []:
            if animation.get("type") == "group":
                animation["duration"] = placement.duration_us

    _sync_keyframes(segment, placement)


def _sync_keyframes(segment: dict, placement) -> None:
    """Кейфреймы перекрывают трансформацию, поэтому их значения тоже правим.

    У QR в шаблонах лежит полный снимок всех свойств — 59 групп по два кадра с
    одинаковым значением. Если поменять только clip.transform, положение вернёт
    кейфрейм KFTypePositionY.
    """
    groups = segment.get("common_keyframes") or []
    if not groups:
        return

    old_duration = max(
        (kf.get("time_offset", 0) for group in groups for kf in group.get("keyframe_list") or []),
        default=0,
    )
    scale = (placement.duration_us / old_duration) if old_duration else 1.0

    clip = segment.get("clip") or {}
    transform = clip.get("transform") or {}
    values = {
        "KFTypePositionY": transform.get("y"),
        "KFTypePositionX": transform.get("x"),
    }

    for group in groups:
        property_type = group.get("property_type")
        for keyframe in group.get("keyframe_list") or []:
            if old_duration:
                keyframe["time_offset"] = int(round(keyframe.get("time_offset", 0) * scale))
            if property_type in values and values[property_type] is not None:
                keyframe["values"] = [float(values[property_type])]


def _apply_music(draft: Draft, profile: TemplateProfile, plan: RenderPlan) -> None:
    if plan.music is None:
        return
    segment = plan.music.ref.get(draft)
    material = draft.find_material(segment.get("material_id")) or {}
    available = int(material.get("duration") or 0)

    source_start = plan.music.source_start_us
    if available and source_start + plan.music.duration_us > available:
        source_start = max(0, available - plan.music.duration_us)

    _set_range(segment, "target_timerange", 0, plan.music.duration_us)
    _set_range(segment, "source_timerange", source_start, plan.music.duration_us)
    segment["volume"] = plan.music.volume


def _refs(draft: Draft, segment: dict, section: str) -> list[dict]:
    index = draft.material_index()
    found = []
    for ref in segment.get("extra_material_refs") or []:
        entry = index.get(ref)
        if entry and entry[0] == section:
            found.append(entry[1])
    return found
