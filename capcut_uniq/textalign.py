"""Подстановка точного текста сценария вместо распознанного.

Распознавание хорошо ловит времена, но ошибается на именах: «Бравл Старс»
превращается то в «Brawl Stars», то в «Бравл Старс» с опечатками. Если рядом с
озвучкой лежит текстовый файл с тем же именем, берём текст оттуда, а времена —
из распознавания, сопоставив последовательности слово к слову.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

from .asr import Word
from .logging_setup import get_logger

log = get_logger("textalign")

_NORMALIZE = re.compile(r"[^0-9a-zа-яё]+", re.IGNORECASE)


def find_script(voice_path: Path) -> Path | None:
    """Ищет сценарий рядом с озвучкой: тем же именем или в подпапке texts."""
    candidates = [
        voice_path.with_suffix(".txt"),
        voice_path.parent / "texts" / f"{voice_path.stem}.txt",
        voice_path.parent / "тексты" / f"{voice_path.stem}.txt",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def normalize(token: str) -> str:
    return _NORMALIZE.sub("", token).lower()


def tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"\s+", text.strip()) if token]


# Слово короче этого на экране не успевает появиться, а нулевой длины — вовсе
# не показывается: реплика из таких слов выходит пустой.
MIN_WORD = 0.08


def realign(words: list[Word], script: str, duration: float = 0.0) -> list[Word]:
    """Возвращает слова сценария с временами из распознавания.

    ``duration`` — длина озвучки. Нужна для слов в конце сценария, которых
    распознавание не услышало: без неё им не остаётся времени и реплика
    получается нулевой длины.
    """
    script_tokens = tokenize(script)
    if not script_tokens or not words:
        return words

    left = [normalize(token) for token in script_tokens]
    right = [normalize(word.text) for word in words]
    matcher = SequenceMatcher(None, left, right, autojunk=False)

    limit = max(duration, words[-1].end)
    result: list[Word] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        count = i2 - i1
        if count <= 0:
            continue

        if tag == "equal":
            for offset in range(count):
                source = words[j1 + offset]
                token = _carry_punctuation(script_tokens[i1 + offset], source.text)
                result.append(Word(token, source.start, source.end))
            continue

        start, end = _span(words, j1, j2, result, limit)
        # Окна может не остаться совсем — тогда раздаём каждому слову минимум,
        # пусть даже с наездом на следующее: пустая реплика хуже неточной.
        if end - start < count * MIN_WORD:
            end = start + count * MIN_WORD
        step = (end - start) / count

        for offset in range(count):
            token_start = start + step * offset
            result.append(Word(script_tokens[i1 + offset], token_start, token_start + step))

    _enforce_minimum(result, limit)

    opcodes = matcher.get_opcodes()
    matched_words = sum(i2 - i1 for tag, i1, i2, _, _ in opcodes if tag == "equal")
    log.debug(
        "текст сценария подставлен: слов в сценарии %d, распознано %d, "
        "времена взяты напрямую у %d, остальным розданы пропорционально",
        len(script_tokens), len(words), matched_words,
    )
    _trace(result, {id(w) for w in result[:0]})
    return result


def _trace(words: list[Word], _unused) -> None:
    """Пишет в журнал каждое слово с временем — по этому видно, где разъехалось."""
    if not log.isEnabledFor(10):  # DEBUG
        return
    log.debug("  слова после выравнивания:")
    for word in words:
        log.debug("    %8.3f..%8.3f  %s", word.start, word.end, word.text)


def _enforce_minimum(words: list[Word], limit: float = 0.0) -> None:
    """Приводит времена в порядок: без нулевых длин, наложений и возвратов назад.

    Возврат назад появляется там, где несовпавшему куску сценария не хватало
    времени и его пришлось растянуть: конец такого куска заезжал на следующий
    участок, и слова начинали идти вразнобой. Анимация подписи от такого текст
    не показывает.

    Сдвигаем только нарушенное, сохраняя естественные паузы. Но сдвиги
    накапливаются, и хвост может уехать за конец озвучки — тогда реплики
    оказались бы за пределами ролика и просто пропали. Поэтому в конце вся
    последовательность при необходимости сжимается назад в отведённое время.
    """
    if not words:
        return

    fixed = 0
    previous_start = float("-inf")
    previous_end = float("-inf")

    for word in words:
        start = word.start
        if start < previous_start:
            start = previous_start
        if start < previous_end:
            start = previous_end
        end = max(word.end, start + MIN_WORD)

        if start != word.start or end != word.end:
            fixed += 1
        word.start, word.end = start, end
        previous_start, previous_end = start, end

    if fixed:
        log.debug("выправлено времён слов: %d", fixed)

    overrun = words[-1].end - limit
    if limit <= 0 or overrun <= 0:
        return

    origin = words[0].start
    span = words[-1].end - origin
    room = limit - origin
    if span <= 0 or room <= 0:
        return

    factor = room / span
    for word in words:
        word.start = origin + (word.start - origin) * factor
        word.end = origin + (word.end - origin) * factor
    log.debug("слова уезжали за озвучку на %.3fс, сжато в %.3fс", overrun, limit)


_PUNCT_TAIL = re.compile(r"[.!?…,;:]+$")


def _carry_punctuation(script_token: str, recognized: str) -> str:
    """Переносит знак препинания из распознавания в текст сценария.

    В сценариях знаков обычно нет, а по ним определяются и границы предложений,
    и места разрыва реплик — CapCut рвёт субтитр в том числе по запятой. На
    экране знаки всё равно не появятся: при сборке субтитра они убираются.
    """
    if _PUNCT_TAIL.search(script_token):
        return script_token
    tail = _PUNCT_TAIL.search(recognized.strip())
    return script_token + tail.group(0) if tail else script_token


def _span(words: list[Word], j1: int, j2: int, emitted: list[Word],
          limit: float) -> tuple[float, float]:
    """Отрезок времени, на который ложится несовпавший кусок сценария."""
    if j2 > j1:
        return words[j1].start, words[j2 - 1].end

    # Сценарий говорит больше, чем услышало распознавание. Внутри текста
    # занимаем промежуток до следующего услышанного слова, а в самом конце —
    # весь остаток озвучки: иначе словам не достаётся времени вообще.
    start = emitted[-1].end if emitted else (words[0].start if words else 0.0)
    if j1 < len(words):
        end = words[j1].start
    else:
        end = limit
    return start, max(start, end)
