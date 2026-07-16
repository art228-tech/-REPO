"""Общий интерфейс провайдера озвучки.

Любой провайдер (Dolphin-браузер или официальный API) реализует один и тот же
интерфейс, поэтому монтаж и оркестратор от способа генерации не зависят —
переключение делается одной строкой в конфиге.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WordTiming:
    word: str
    start: float
    end: float


@dataclass
class TTSResult:
    audio_path: Path
    duration: float
    words: list[WordTiming] = field(default_factory=list)


class VoiceProviderError(Exception):
    """Ошибка провайдера озвучки (не роняет процесс — ловится оркестратором)."""


class VoiceProvider(ABC):
    """Контракт провайдера озвучки."""

    @abstractmethod
    def login(self) -> None:
        """Подготовить доступ (открыть профиль/проверить ключ)."""

    @abstractmethod
    def create_voice(self, description: str, name: str) -> str:
        """Создать голос из текстового промпта (Voice Design). Вернуть voice_id."""

    @abstractmethod
    def tts(self, text: str, voice_id: str, out_path: Path) -> TTSResult:
        """Озвучить текст выбранным голосом, сохранить аудио, вернуть тайминги."""

    @abstractmethod
    def tokens_left(self) -> int | None:
        """Остаток символов/кредитов (или None, если неизвестно)."""

    def close(self) -> None:  # noqa: B027 - опциональный хук очистки
        """Освободить ресурсы (закрыть/удалить созданный профиль браузера)."""


def clamp_voice_description(desc: str, min_len: int, max_len: int) -> str:
    """Подогнать описание голоса под лимит [min_len, max_len] символов.

    Требование пользователя: слишком длинный промпт НЕ должен останавливать
    софт. Поэтому длинный — обрезаем по границе слова, короткий — дополняем
    нейтральным хвостом, и обязательно логируем на стороне вызова.
    """
    desc = desc.strip()
    if len(desc) > max_len:
        cut = desc[:max_len]
        # обрезаем по последнему пробелу, чтобы не рвать слово
        last_space = cut.rfind(" ")
        if last_space > 0:
            cut = cut[:last_space]
        return cut.strip()
    if len(desc) < min_len:
        pad = " Natural, clear, expressive narration voice."
        while len(desc) < min_len:
            desc = (desc + pad).strip()
        return desc[:max_len]
    return desc


def split_text_for_tts(text: str, char_limit: int) -> list[str]:
    """Разбить длинный текст на куски <= char_limit по границам предложений.

    Никогда не роняет из-за длины — просто режет и склеивает.
    """
    text = text.strip()
    if len(text) <= char_limit:
        return [text] if text else []

    import re
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    chunks: list[str] = []
    current = ""
    for sent in sentences:
        if len(sent) > char_limit:
            # Слишком длинное предложение — режем по словам.
            words = sent.split()
            for word in words:
                if len(current) + len(word) + 1 > char_limit:
                    if current:
                        chunks.append(current.strip())
                    current = word
                else:
                    current = f"{current} {word}".strip()
            continue
        if len(current) + len(sent) + 1 > char_limit:
            chunks.append(current.strip())
            current = sent
        else:
            current = f"{current} {sent}".strip()
    if current.strip():
        chunks.append(current.strip())
    return chunks
