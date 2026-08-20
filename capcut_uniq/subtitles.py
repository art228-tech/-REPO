"""Сборка субтитров в формате CapCut.

Оформление не воспроизводится, а наследуется: берём текстовый шаблон, текстовый
материал и анимацию прямо из исходного проекта и клонируем их под каждую новую
реплику. Меняются только текст, тайминги и размеры текстового блока.

Связь объектов в черновике такая:
    сегмент → text_template → text_info_resources[0].text_material_id → text
Анимация субтитра лежит в extra_material_refs внутри text_info_resources.
"""
from __future__ import annotations

import copy
import json
import re
import time

from .config import Timing
from .draft_io import Draft, new_capcut_id
from .logging_setup import get_logger
from .plan import Cue
from .profile import TemplateProfile
from .units import s2ms, s2us
from .asr import Transcript

log = get_logger("subtitles")

TRAILING_PUNCT = re.compile(r"[.,!?;:…«»\"()]+$")
LEADING_PUNCT = re.compile(r"^[«\"(]+")


def clean_word(text: str) -> str:
    """CapCut в автосубтитрах не показывает знаки препинания — убираем и мы."""
    return LEADING_PUNCT.sub("", TRAILING_PUNCT.sub("", text)).strip()


def build_cues(transcript: Transcript, timing: Timing) -> list[Cue]:
    """Разбивает распознанную речь на реплики: по паузам и по длине строки."""
    if not transcript.has_words:
        return []

    # Порог, после которого строку уже можно закрыть на любой заметной паузе.
    # Без него длинные фразы рвутся ровно по счётчику символов и реплика может
    # закончиться на предлоге — в исходных шаблонах такого нет.
    comfortable = int(timing.subtitle_max_chars * 0.6)

    groups: list[list] = [[]]
    for previous, word in zip([None, *transcript.words], transcript.words):
        current = groups[-1]
        gap = (word.start - previous.end) if previous else 0.0
        pending = " ".join(clean_word(w.text) for w in current)
        length = len(pending) + 1 + len(clean_word(word.text))
        too_long = length > timing.subtitle_max_chars
        previous_text = previous.text.strip() if previous else ""
        sentence_break = bool(re.search(r"[.!?…]$", previous_text))
        # Запятая — мягкая граница: рвём по ней, только если строка уже набрала
        # заметную длину. Так же ведут себя автосубтитры самого CapCut.
        comma_break = bool(re.search(r"[,;:]$", previous_text)) and len(pending) >= comfortable
        natural_break = gap >= 0.15 and len(pending) >= comfortable

        if current and (gap >= timing.subtitle_gap_s or too_long or sentence_break
                        or comma_break or natural_break):
            groups.append([word])
        else:
            current.append(word)

    cues: list[Cue] = []
    for group in groups:
        words = [(clean_word(w.text), w.start, w.end) for w in group]
        words = [(text, start, end) for text, start, end in words if text]
        if not words:
            continue
        start = words[0][1]
        end = words[-1][2]
        text = " ".join(text for text, _, _ in words)
        cues.append(Cue(
            text=text,
            start_us=s2us(start),
            duration_us=max(1, s2us(end - start)),
            words=[(text, s2ms(w_start - start), s2ms(w_end - start)) for text, w_start, w_end in words],
        ))

    _widen_short(cues)
    log.debug("собрано реплик: %d", len(cues))
    return cues


# Реплика короче этого на экране не читается, а совсем короткая просто не видна.
# В исходных шаблонах самая быстрая занимала 0.24 секунды.
MIN_CUE_US = 300_000
CUE_GAP_US = 40_000


def _widen_short(cues: list[Cue]) -> None:
    """Растягивает слишком короткие реплики, не наезжая на следующую.

    Короткие берутся оттуда, где распознавание не услышало часть сценария:
    словам не достаётся времени, и реплика выходит длиной в микросекунды —
    на экране её попросту нет.
    """
    widened = 0
    for position, cue in enumerate(cues):
        if cue.duration_us >= MIN_CUE_US:
            continue
        limit = MIN_CUE_US
        if position + 1 < len(cues):
            available = cues[position + 1].start_us - CUE_GAP_US - cue.start_us
            limit = min(limit, max(1, available))
        if limit > cue.duration_us:
            cue.duration_us = limit
            widened += 1
    if widened:
        log.debug("растянуто слишком коротких реплик: %d", widened)


def _word_arrays(cue: Cue) -> dict:
    """Массивы для поля ``words``: между словами стоят пробелы нулевой длины."""
    starts: list[int] = []
    ends: list[int] = []
    tokens: list[str] = []
    for index, (text, start_ms, end_ms) in enumerate(cue.words):
        if index:
            previous_end = ends[-1]
            starts.append(previous_end)
            ends.append(previous_end)
            tokens.append(" ")
        starts.append(start_ms)
        ends.append(end_ms)
        tokens.append(text)
    return {"start_time": starts, "end_time": ends, "text": tokens}


def _size_for(style_metrics: list[tuple[int, float, float]], length: int) -> tuple[float, float]:
    """Размер текстового блока: берём ближайший по длине из шаблона.

    CapCut пересчитывает эти значения при открытии проекта, поэтому точность
    здесь нужна только чтобы превью не дёргалось на первом кадре.
    """
    usable = [m for m in style_metrics if m[1] > 0]
    if not usable:
        return 574.0, 120.0
    closest = min(usable, key=lambda m: abs(m[0] - length))
    return closest[1], closest[2]


def _fill_text(base_text: dict, cue: Cue, group_id: str) -> tuple[str, dict]:
    """Клон текстового материала с новым содержимым."""
    material = copy.deepcopy(base_text)
    text_id = new_capcut_id()
    material["id"] = text_id
    material["name"] = new_capcut_id()
    material["recognize_text"] = cue.text
    material["group_id"] = group_id
    material["words"] = _word_arrays(cue)
    material["current_words"] = {"start_time": [], "end_time": [], "text": []}

    body = json.loads(material.get("content") or "{}")
    body["text"] = cue.text
    # Диапазон оформления считается в символах, поэтому его надо пересчитать.
    for entry in body.get("styles") or []:
        entry["range"] = [0, len(cue.text)]
    material["content"] = json.dumps(body, ensure_ascii=False)
    return text_id, material


def apply(draft: Draft, profile: TemplateProfile, cues: list[Cue]) -> int:
    """Заменяет дорожку субтитров на новую. Возвращает число реплик."""
    style = profile.subtitles
    if style is None:
        return 0

    materials = draft.materials
    templates = materials.setdefault("text_templates", [])
    texts = materials.setdefault("texts", [])
    animations = materials.setdefault("material_animations", [])

    base_text = next((t for t in texts if t.get("id") == style.text_material_id), None)
    base_template = None
    if style.kind == "template":
        base_template = next((t for t in templates if t.get("id") == style.template_material_id), None)
        if base_template is None:
            log.warning("В шаблоне не нашёлся эталонный текстовый шаблон, дорожка не тронута")
            return 0
    if base_text is None:
        log.warning("В шаблоне не нашёлся эталонный текст субтитра, дорожка не тронута")
        return 0

    base_animation = next((a for a in animations if a.get("id") == style.animation_id), None)
    track = draft.tracks[style.track]
    base_segment = copy.deepcopy(track["segments"][0])
    base_refs = [r for r in (base_segment.get("extra_material_refs") or [])]

    stale = _collect_stale_ids(draft, track)
    materials["text_templates"] = [t for t in templates if t.get("id") not in stale]
    materials["texts"] = [t for t in texts if t.get("id") not in stale]
    materials["material_animations"] = [a for a in animations if a.get("id") not in stale]

    group_id = f"ru-RU_{int(time.time() * 1000)}"
    segments: list[dict] = []

    for position, cue in enumerate(cues):
        text_id, text_material = _fill_text(base_text, cue, group_id)
        materials["texts"].append(text_material)

        animation_id = None
        if base_animation is not None:
            animation = copy.deepcopy(base_animation)
            animation_id = new_capcut_id()
            animation["id"] = animation_id
            for item in animation.get("animations") or []:
                item["duration"] = cue.duration_us
                item["start"] = 0
            materials["material_animations"].append(animation)

        if style.kind == "template":
            template = copy.deepcopy(base_template)
            segment_material_id = new_capcut_id()
            template["id"] = segment_material_id
            width, height = _size_for(style.metrics, len(cue.text))
            for resource in template.get("text_info_resources") or []:
                resource["text_material_id"] = text_id
                resource["extra_material_refs"] = [animation_id] if animation_id else []
                attach = resource.setdefault("attach_info", {})
                attach["start_time"] = 0
                attach["duration"] = cue.duration_us
                attach["original_size_width"] = width
                attach["original_size_height"] = height
            materials["text_templates"].append(template)
        else:
            segment_material_id = text_id

        segment = copy.deepcopy(base_segment)
        segment["id"] = new_capcut_id()
        segment["material_id"] = segment_material_id
        segment["target_timerange"] = {"start": cue.start_us, "duration": cue.duration_us}
        # Прочие ссылки сегмента сохраняем, подменяя только анимацию.
        refs = [r for r in base_refs if r not in stale]
        if animation_id:
            refs.append(animation_id)
        segment["extra_material_refs"] = refs
        segment["render_index"] = style.render_index + position
        segments.append(segment)

    track["segments"] = segments
    log.debug("дорожка субтитров пересобрана: %d реплик (устройство %s)", len(segments), style.kind)
    return len(segments)


def _collect_stale_ids(draft: Draft, track: dict) -> set[str]:
    """Идентификаторы объектов, которые обслуживали старые субтитры."""
    index = draft.material_index()
    stale: set[str] = set()
    for segment in track.get("segments") or []:
        material_id = segment.get("material_id")
        if not material_id:
            continue
        stale.add(material_id)
        stale.update(segment.get("extra_material_refs") or [])
        entry = index.get(material_id)
        if not entry:
            continue
        for resource in entry[1].get("text_info_resources") or []:
            if resource.get("text_material_id"):
                stale.add(resource["text_material_id"])
            stale.update(resource.get("extra_material_refs") or [])
    return stale


def clear(draft: Draft, profile: TemplateProfile) -> int:
    """Полностью убирает субтитры — режим, когда пользователь делает их сам."""
    style = profile.subtitles
    if style is None:
        return 0
    track = draft.tracks[style.track]
    stale = _collect_stale_ids(draft, track)
    removed = len(track.get("segments") or [])
    track["segments"] = []
    for section in ("text_templates", "texts", "material_animations"):
        items = draft.materials.get(section) or []
        draft.materials[section] = [item for item in items if item.get("id") not in stale]
    return removed
