"""Провайдер озвучки через официальный API ElevenLabs (один аккаунт).

Стабильный путь: Voice Design для создания голоса из промпта + TTS.
Требует переменную окружения с ключом (см. config: voice.elevenlabs_api).
"""
from __future__ import annotations

import os
from pathlib import Path

from ..logging_setup import get_logger
from .base import (TTSResult, VoiceProvider, VoiceProviderError, WordTiming,
                   clamp_voice_description)

log = get_logger("voice.elevenlabs_api")


class ElevenLabsApiProvider(VoiceProvider):
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.model = cfg.get("model", "eleven_multilingual_v2")
        api_cfg = cfg.get("elevenlabs_api", {})
        self.ttv_model = api_cfg.get("ttv_model", "eleven_multilingual_ttv_v2")
        self.desc_min = int(cfg.get("voice_desc_min", 20))
        self.desc_max = int(cfg.get("voice_desc_max", 1000))
        key_env = api_cfg.get("api_key_env", "ELEVENLABS_API_KEY")
        self.api_key = os.getenv(key_env, "")
        self._client = None

    def login(self) -> None:
        if not self.api_key:
            raise VoiceProviderError(
                "Не задан ключ ElevenLabs. Добавь секрет ELEVENLABS_API_KEY "
                "(Cursor Dashboard → Cloud Agents → Secrets) или в окружение."
            )
        try:
            from elevenlabs.client import ElevenLabs
        except ImportError as exc:
            raise VoiceProviderError(
                "Пакет elevenlabs не установлен. pip install elevenlabs"
            ) from exc
        self._client = ElevenLabs(api_key=self.api_key)
        log.info("Официальный API ElevenLabs готов (модель TTS: %s).", self.model)

    def create_voice(self, description: str, name: str) -> str:
        desc = clamp_voice_description(description, self.desc_min, self.desc_max)
        if desc != description.strip():
            log.warning("Описание голоса '%s' подогнано под лимит "
                        "%d..%d символов.", name, self.desc_min, self.desc_max)
        try:
            previews = self._client.text_to_voice.design(
                model_id=self.ttv_model,
                voice_description=desc,
                text=("Пример звучания голоса для проверки качества и тембра "
                      "перед сохранением в библиотеку голосов."),
            )
            gen_id = previews.previews[0].generated_voice_id
            voice = self._client.text_to_voice.create(
                voice_name=name,
                voice_description=desc,
                generated_voice_id=gen_id,
            )
            log.info("Создан голос '%s' -> voice_id=%s", name, voice.voice_id)
            return voice.voice_id
        except Exception as exc:  # noqa: BLE001 - оборачиваем в понятную ошибку
            raise VoiceProviderError(f"Не удалось создать голос '{name}': {exc}") \
                from exc

    def tts(self, text: str, voice_id: str, out_path: Path) -> TTSResult:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Просим тайминги по символам, чтобы построить субтитры.
            resp = self._client.text_to_speech.convert_with_timestamps(
                voice_id=voice_id,
                text=text,
                model_id=self.model,
                output_format="mp3_44100_128",
            )
            audio_bytes = _extract_audio_bytes(resp)
            out_path.write_bytes(audio_bytes)
            words = _words_from_char_timestamps(text, resp)
            duration = words[-1].end if words else 0.0
            log.info("Озвучено %d символов -> %s", len(text), out_path.name)
            return TTSResult(audio_path=out_path, duration=duration, words=words)
        except Exception as exc:  # noqa: BLE001
            raise VoiceProviderError(f"Ошибка TTS: {exc}") from exc

    def tokens_left(self) -> int | None:
        try:
            sub = self._client.user.subscription.get()
            return int(sub.character_limit - sub.character_count)
        except Exception:  # noqa: BLE001
            return None


def _extract_audio_bytes(resp) -> bytes:
    # SDK может вернуть объект с полем audio_base64 или готовые байты.
    import base64
    audio = getattr(resp, "audio_base_64", None) or getattr(resp, "audio_base64", None)
    if audio:
        return base64.b64decode(audio)
    if isinstance(resp, (bytes, bytearray)):
        return bytes(resp)
    raise VoiceProviderError("Не удалось извлечь аудио из ответа API.")


def _words_from_char_timestamps(text: str, resp) -> list[WordTiming]:
    """Свести посимвольные тайминги ElevenLabs к словам."""
    alignment = getattr(resp, "alignment", None)
    if not alignment:
        return []
    chars = getattr(alignment, "characters", []) or []
    starts = getattr(alignment, "character_start_times_seconds", []) or []
    ends = getattr(alignment, "character_end_times_seconds", []) or []
    words: list[WordTiming] = []
    buf = ""
    w_start = None
    w_end = 0.0
    for ch, st, en in zip(chars, starts, ends):
        if ch.isspace():
            if buf:
                words.append(WordTiming(buf, w_start or 0.0, w_end))
                buf = ""
                w_start = None
            continue
        if w_start is None:
            w_start = st
        buf += ch
        w_end = en
    if buf:
        words.append(WordTiming(buf, w_start or 0.0, w_end))
    return words
