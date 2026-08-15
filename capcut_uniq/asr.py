"""Распознавание озвучки.

Отсюда берутся две вещи: слова с временами для субтитров и границы предложений
для точки стыка короткого и длинного фрагментов. Если модель распознавания
недоступна, остаётся запасной режим по тишине — субтитров он не даёт, но
позволяет найти стык.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import ffmpeg
from .errors import AudioError, ToolMissing
from .logging_setup import get_logger

log = get_logger("asr")

SENTENCE_END = re.compile(r"[.!?…]+[\"»)]*$")

_model_cache: dict[tuple[str, str], object] = {}


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Transcript:
    duration: float
    words: list[Word] = field(default_factory=list)
    source: str = "whisper"
    pauses: list[tuple[float, float]] = field(default_factory=list)
    marks: list[float] = field(default_factory=list)
    """Концы предложений по исходному распознаванию. Хранятся отдельно, потому
    что при подстановке текста сценария знаки препинания могут пропасть."""

    @property
    def has_words(self) -> bool:
        return bool(self.words)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words).strip()

    def sentence_ends(self) -> list[float]:
        """Моменты окончания предложений."""
        ends = [w.end for w in self.words if SENTENCE_END.search(w.text.strip())]
        if ends:
            return ends
        if self.marks:
            return list(self.marks)
        # Знаков нет вовсе — считаем границей любую заметную паузу.
        return [end for _, end in self.gaps(0.45)]

    def gaps(self, min_gap: float) -> list[tuple[float, float]]:
        """Паузы между словами длиннее заданной: список (начало, конец)."""
        result: list[tuple[float, float]] = []
        for previous, current in zip(self.words, self.words[1:]):
            if current.start - previous.end >= min_gap:
                result.append((previous.end, current.start))
        if not self.words:
            result.extend(self.pauses)
        return result


def transcribe(path: Path, model_name: str = "small", language: str = "ru") -> Transcript:
    """Распознаёт файл. При отсутствии модели переходит в режим по тишине."""
    duration = ffmpeg.probe(path).duration_s
    try:
        words = _whisper_words(path, model_name, language)
    except ToolMissing as exc:
        log.warning("%s — работаю по тишине, субтитры собрать не смогу", exc)
        return _silence_transcript(path, duration)

    if not words:
        log.warning("В %s не распознано ни одного слова, перехожу на разбор по тишине", path.name)
        return _silence_transcript(path, duration)

    log.debug("%s: распознано %d слов, текст: %s", path.name, len(words),
              " ".join(w.text for w in words)[:160])
    marks = [w.end for w in words if SENTENCE_END.search(w.text.strip())]
    return Transcript(duration=duration, words=words, source="whisper", marks=marks)


def _silence_transcript(path: Path, duration: float) -> Transcript:
    intervals = ffmpeg.silences(path)
    inner = [(start, end) for start, end in intervals if end < duration - 1e-3]
    return Transcript(duration=duration, words=[], source="silence", pauses=inner)


def _whisper_words(path: Path, model_name: str, language: str) -> list[Word]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise ToolMissing(
            "Не установлен faster-whisper, поэтому распознавание речи недоступно. "
            "Поставь его командой: pip install faster-whisper"
        ) from exc

    key = (model_name, language)
    model = _model_cache.get(key)
    if model is None:
        log.info("Загружаю модель распознавания «%s» (первый раз может занять время)", model_name)
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        _model_cache[key] = model

    segments, _info = model.transcribe(
        str(path),
        language=language,
        word_timestamps=True,
        vad_filter=True,
    )

    words: list[Word] = []
    for segment in segments:
        for word in getattr(segment, "words", None) or []:
            text = (word.word or "").strip()
            if not text:
                continue
            words.append(Word(text=text, start=float(word.start), end=float(word.end)))

    if words and words[-1].end <= 0:
        raise AudioError(f"Распознавание {path.name} вернуло некорректные времена")
    return words


def pick_cut_point(
    transcript: Transcript,
    lower: float,
    upper: float,
) -> tuple[float, str]:
    """Точка стыка короткого и длинного фрагментов.

    Правило: берём конец первого предложения. Если он позже верхней границы —
    ищем самую позднюю паузу внутри коридора. Нет и её — упираемся в границу.
    Раньше нижней границы — растягиваем до неё.
    """
    ends = [value for value in transcript.sentence_ends() if value > 0]
    first = ends[0] if ends else None

    if first is not None and lower <= first <= upper:
        return first, "конец первого предложения"

    if first is not None and first < lower:
        return lower, f"первое предложение кончилось на {first:.3f}с, растянуто до нижнего предела"

    # Предложение затянулось за верхнюю границу (или его вовсе не нашли) —
    # ищем внутри коридора самую заметную паузу, чтобы стык не резал слово.
    candidates = [(end - start, end) for start, end in transcript.gaps(0.08) if lower <= end <= upper]
    candidates += [(0.0, end) for end in ends if lower <= end <= upper]
    if candidates:
        _, chosen = max(candidates)
        if first is None:
            return chosen, f"границ предложений нет, взята самая длинная пауза на {chosen:.3f}с"
        return chosen, f"предложение длиннее предела, взята пауза на {chosen:.3f}с"

    if first is None:
        log.warning("Ни границ предложений, ни пауз в коридоре — ставлю стык на %.3fс", upper)
        return upper, "нет ни границ предложений, ни пауз, взят верхний предел"

    return upper, f"первое предложение кончилось на {first:.3f}с, пауз в коридоре нет, взят предел"
