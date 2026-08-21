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
import random
import re
import string
import time

from dataclasses import dataclass

from .config import Timing
from .draft_io import Draft, new_capcut_id
from .logging_setup import get_logger
from .plan import Cue
from .profile import TemplateProfile
from .units import s2ms, s2us
from .asr import Transcript

log = get_logger("subtitles")


@dataclass(frozen=True)
class Way:
    """Способ записать субтитры в черновик.

    Нужен для перебора: CapCut не рассказывает, почему не рисует текст, поэтому
    один и тот же ролик собирается несколькими способами, и по готовым роликам
    видно, какой работает.
    """

    name: str = "как сейчас"
    note: str = ""
    ids: str = "uuid"           # uuid | capcut | template
    words: str = "computed"     # computed | template | empty
    animation: bool = True
    device: str = "auto"        # auto | text
    size: str = "measured"      # measured | template


DEFAULT_WAY = Way()


def _capcut_style_id() -> str:
    """Идентификатор в том же виде, в каком их пишет сам CapCut."""
    alphabet = string.ascii_uppercase + string.digits
    parts = (8, 4, 4, 4, 12)
    return "-".join(
        "".join(random.choice(alphabet) for _ in range(size)) for size in parts
    )


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

        reason = ""
        if current:
            if sentence_break:
                reason = "конец предложения"
            elif gap >= timing.subtitle_gap_s:
                reason = f"пауза {gap:.2f}с"
            elif too_long:
                reason = f"длина {length} символов"
            elif comma_break:
                reason = "запятая"
            elif natural_break:
                reason = f"пауза {gap:.2f}с при длине {len(pending)}"

        if reason:
            log.debug("  разрыв реплики перед «%s»: %s", clean_word(word.text), reason)
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
        # Границу считаем от абсолютных времён, а не как начало плюс длина:
        # независимое округление давало наложение соседних реплик на
        # микросекунду, и CapCut считал такой черновик битым.
        start_us = s2us(start)
        end_us = s2us(end)
        cues.append(Cue(
            text=text,
            start_us=start_us,
            duration_us=max(1, end_us - start_us),
            words=[(text, s2ms(w_start - start), s2ms(w_end - start)) for text, w_start, w_end in words],
        ))

    _widen_short(cues)
    log.debug("собрано реплик: %d", len(cues))
    for position, cue in enumerate(cues):
        arrays = _word_arrays(cue)
        log.debug(
            "  реплика %d: %s..%s (%d мс), символов %d, слов %d, край слов %d мс — %r",
            position,
            f"{cue.start_us / 1e6:.3f}",
            f"{(cue.start_us + cue.duration_us) / 1e6:.3f}",
            cue.duration_us // 1000,
            len(cue.text),
            len(cue.words),
            max(arrays["end_time"]) if arrays["end_time"] else 0,
            cue.text,
        )
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


def _fit_words(cue: Cue) -> list[tuple[str, int, int]]:
    """Подгоняет времена слов ровно под длительность реплики.

    В исходных шаблонах последнее слово всегда кончается точно на краю реплики —
    это не совпадение, а то, от чего отсчитывает анимация подписи. Если слова
    уезжают за край или, наоборот, не добирают до него, анимация показывает
    не всё, а то и вовсе ничего.
    """
    limit = max(1, cue.duration_us // 1000)
    if not cue.words:
        return []

    last = max(end for _, _, end in cue.words)
    if last <= 0:
        # Времён нет вовсе — раскладываем слова ровно по реплике.
        step = limit / len(cue.words)
        return [
            (text, int(round(step * position)), int(round(step * (position + 1))))
            for position, (text, _, _) in enumerate(cue.words)
        ]

    factor = limit / last
    fitted: list[tuple[str, int, int]] = []
    for text, start, end in cue.words:
        fitted.append((text, int(round(start * factor)), int(round(end * factor))))

    # Округление могло сдвинуть край на миллисекунду — доводим точно.
    text, start, _ = fitted[-1]
    fitted[-1] = (text, min(start, limit - 1), limit)
    return fitted


def word_arrays(cue: Cue) -> dict:
    """Разбиение реплики по словам в том виде, в каком его ждёт CapCut."""
    return _word_arrays(cue)


def size_for(metrics, length: int) -> tuple[float, float]:
    """Размер надписи под длину текста, по замерам шаблона."""
    return _size_for(metrics, length)


def _word_arrays(cue: Cue) -> dict:
    """Массивы для поля ``words``: между словами стоят пробелы нулевой длины."""
    starts: list[int] = []
    ends: list[int] = []
    tokens: list[str] = []
    for index, (text, start_ms, end_ms) in enumerate(_fit_words(cue)):
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


def _fill_text(base_text: dict, cue: Cue, group_id: str,
               text_id: str | None = None, way: Way = DEFAULT_WAY) -> tuple[str, dict]:
    """Клон текстового материала с новым содержимым."""
    material = copy.deepcopy(base_text)
    text_id = text_id or new_capcut_id()
    material["id"] = text_id
    material["name"] = new_capcut_id()
    material["recognize_text"] = cue.text
    material["group_id"] = group_id

    empty = {"start_time": [], "end_time": [], "text": []}
    if way.words == "template":
        material["words"] = copy.deepcopy(base_text.get("words") or empty)
    elif way.words == "empty":
        material["words"] = dict(empty)
    else:
        material["words"] = _word_arrays(cue)
    material["current_words"] = dict(empty)

    material["content"] = rewrite_content(material.get("content") or "{}", cue.text)
    return text_id, material


_TEXT_VALUE = re.compile(r'("text"\s*:\s*)("(?:[^"\\]|\\.)*")')
_RANGE_VALUE = re.compile(r'("range"\s*:\s*\[\s*\d+\s*,\s*)(\d+)(\s*\])')


def rewrite_content(original: str, text: str) -> str:
    """Подставляет новый текст в оформление субтитра, не переписывая остальное.

    Оформление лежит в черновике как JSON внутри строки. Если разобрать его и
    собрать заново, меняется всё: CapCut пишет без пробелов, а Python — с
    пробелами после запятых и двоеточий, и вдобавок сокращает запись дробных
    чисел (0.059999998658895493 превращается в 0.05999999865889549). Значение
    то же, а байты другие.

    Поэтому правим строку на месте: меняем только сам текст и диапазон
    оформления, который считается в символах. Всё остальное остаётся точно
    таким, как его записал CapCut.
    """
    body = json.loads(original or "{}")
    old_text = body.get("text") or ""

    # Диапазон, покрывавший строку целиком, тянется за новой длиной. Диапазон
    # части строки трогать нельзя: он про своё, а не про длину текста.
    expected = copy.deepcopy(body)
    expected["text"] = text
    for entry in expected.get("styles") or []:
        span = entry.get("range")
        if isinstance(span, list) and len(span) == 2 and span[1] == len(old_text):
            entry["range"] = [span[0], len(text)]

    result = _RANGE_VALUE.sub(
        lambda m: m.group(1) + str(len(text)) + m.group(3)
        if int(m.group(2)) == len(old_text) else m.group(0),
        original,
    )

    # Ключ "text" CapCut пишет последним, поэтому берём последнее совпадение с
    # прежним текстом — так не задеть одноимённые ключи внутри оформления.
    encoded = json.dumps(text, ensure_ascii=False)
    matches = [m for m in _TEXT_VALUE.finditer(result)
               if json.loads(m.group(2)) == old_text]
    if matches:
        last = matches[-1]
        result = result[:last.start()] + last.group(1) + encoded + result[last.end():]

    try:
        if json.loads(result) == expected:
            return result
    except ValueError:
        pass

    log.debug("оформление субтитра не поддалось точечной правке, собираю заново")
    return json.dumps(expected, ensure_ascii=False, separators=(",", ":"))


def apply(draft: Draft, profile: TemplateProfile, cues: list[Cue],
          way: Way = DEFAULT_WAY, borrow: list[dict] | None = None) -> int:
    """Заменяет дорожку субтитров на новую. Возвращает число реплик.

    ``borrow`` — опознаватели, которые нужно занять вместо новых. Нужен перебору:
    копия собирается из готового ролика, а занять надо опознаватели шаблона.
    """
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

    original = borrow if borrow is not None else _original_ids(draft, track)

    def make_id(position: int, role: str) -> str:
        if way.ids == "capcut":
            return _capcut_style_id()
        if way.ids == "template" and position < len(original):
            found = original[position].get(role)
            if found:
                return found
        return new_capcut_id()

    stale = _collect_stale_ids(draft, track)
    materials["text_templates"] = [t for t in templates if t.get("id") not in stale]
    materials["texts"] = [t for t in texts if t.get("id") not in stale]
    materials["material_animations"] = [a for a in animations if a.get("id") not in stale]

    group_id = f"ru-RU_{int(time.time() * 1000)}"
    segments: list[dict] = []

    for position, cue in enumerate(cues):
        text_id, text_material = _fill_text(
            base_text, cue, group_id, make_id(position, "text"), way)
        if way.words == "template" and position < len(original):
            occupied = original[position].get("words")
            if occupied:
                text_material["words"] = copy.deepcopy(occupied)
        materials["texts"].append(text_material)

        animation_id = None
        if base_animation is not None and way.animation:
            animation = copy.deepcopy(base_animation)
            animation_id = make_id(position, "animation")
            animation["id"] = animation_id
            for item in animation.get("animations") or []:
                item["duration"] = cue.duration_us
                item["start"] = 0
            materials["material_animations"].append(animation)

        if style.kind == "template" and way.device != "text":
            template = copy.deepcopy(base_template)
            segment_material_id = make_id(position, "template")
            template["id"] = segment_material_id
            width, height = _size_for(style.metrics, len(cue.text))
            if way.size == "template":
                first = (base_template.get("text_info_resources") or [{}])[0]
                attach = first.get("attach_info") or {}
                width = attach.get("original_size_width", width)
                height = attach.get("original_size_height", height)
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
        segment["id"] = make_id(position, "segment")
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


def original_ids(draft: Draft, track: int) -> list[dict]:
    """Опознаватели субтитров по порядку у дорожки с указанным номером."""
    return _original_ids(draft, draft.tracks[track])


def _original_ids(draft: Draft, track: dict) -> list[dict]:
    """Идентификаторы субтитров шаблона по порядку — чтобы можно было их занять."""
    index = draft.material_index()
    rows: list[dict] = []
    for segment in track.get("segments") or []:
        row = {"segment": segment.get("id"), "template": segment.get("material_id")}
        found = index.get(segment.get("material_id"))
        if found and found[0] == "text_templates":
            for resource in found[1].get("text_info_resources") or []:
                row["text"] = resource.get("text_material_id")
                refs = resource.get("extra_material_refs") or []
                if refs:
                    row["animation"] = refs[0]
                break
        else:
            row["text"] = segment.get("material_id")
            refs = segment.get("extra_material_refs") or []
            if refs:
                row["animation"] = refs[0]

        text_material = index.get(row.get("text"))
        if text_material and text_material[0] == "texts":
            row["words"] = text_material[1].get("words")
        rows.append(row)
    return rows


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
