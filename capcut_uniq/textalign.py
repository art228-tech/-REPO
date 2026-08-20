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

    _enforce_minimum(result)
    matched = sum(1 for tag, *_ in matcher.get_opcodes() if tag == "equal")
    log.debug(
        "текст сценария подставлен: %d слов, совпавших участков %d",
        len(result), matched,
    )
    return result


def _enforce_minimum(words: list[Word]) -> None:
    """Гарантирует, что ни одно слово не осталось нулевой длины."""
    fixed = 0
    for word in words:
        if word.end - word.start < MIN_WORD:
            word.end = word.start + MIN_WORD
            fixed += 1
    if fixed:
        log.debug("растянуто до минимальной длины слов: %d", fixed)


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
