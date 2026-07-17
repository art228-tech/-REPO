"""Оркестратор озвучки (отдельный процесс от монтажа).

Логика (как описал пользователь):
  1. Взять промпты голосов по порядку и создать N голосов (voices_per_run).
  2. Идти по текстам: голос1 -> текст, голос2 -> следующий текст, по кругу.
  3. Каждую озвучку класть в папку + рядом json с таймингами слов (для субтитров).
  4. Уважать режимы папок (cycle / consume) и число циклов.
  5. Всё пишется в state — при сбое запуск продолжается без потерь.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import Config
from ..logging_setup import get_logger
from ..state import StateStore
from .base import (TTSResult, VoiceProvider, VoiceProviderError,
                   split_text_for_tts)

log = get_logger("voice.pipeline")


def get_provider(cfg: Config, account: dict | None = None) -> VoiceProvider:
    provider = cfg.voice_provider
    if provider == "dolphin":
        from .dolphin import DolphinProvider
        return DolphinProvider(cfg.voice, account=account)
    if provider == "elevenlabs_api":
        from .elevenlabs_api import ElevenLabsApiProvider
        return ElevenLabsApiProvider(cfg.voice)
    raise VoiceProviderError(f"Неизвестный провайдер озвучки: {provider}")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def ensure_voices(provider: VoiceProvider, cfg: Config, pools, state: StateStore) -> list[str]:
    """Создать голоса из промптов (или взять уже созданные из state)."""
    existing = state.get("voice_ids", [])
    want = int(cfg.voice.get("voices_per_run", 3))
    if len(existing) >= want:
        log.info("Голоса уже созданы ранее: %s", existing)
        return existing[:want]

    pool = pools.get("voice_prompts")
    if pool is None:
        raise VoiceProviderError("Нет папки voice_prompts в конфиге.")

    voice_ids = list(existing)
    for i in range(len(existing), want):
        prompt_file = pool.next()
        if prompt_file is None:
            log.warning("Промпты голосов закончились на %d из %d.", i, want)
            break
        desc = _read_text(prompt_file)
        try:
            vid = provider.create_voice(desc, name=f"autoshorts-{i+1}")
            voice_ids.append(vid)
            state.set("voice_ids", voice_ids)  # чекпоинт после каждого голоса
            pool.mark_consumed(prompt_file)
        except VoiceProviderError as exc:
            log.error("Голос %d не создан: %s", i + 1, exc)
    return voice_ids


def run_voice(cfg: Config, cycles: int, account: dict | None = None) -> list[dict]:
    """Сгенерировать `cycles` озвучек. Вернуть список описаний результатов."""
    from ..assets import build_pools

    state = StateStore(Path(cfg.state_dir) / "voice_state.json")
    pools = build_pools(cfg.folders, state)
    out_dir = Path(cfg.voice.get("output_dir", "assets/voiceovers"))
    out_dir.mkdir(parents=True, exist_ok=True)
    char_limit = int(cfg.voice.get("tts_char_limit", 10000))

    provider = get_provider(cfg, account=account)
    results: list[dict] = []
    try:
        provider.login()
        voice_ids = ensure_voices(provider, cfg, pools, state)
        if not voice_ids:
            raise VoiceProviderError("Не создано ни одного голоса — нет промптов?")

        scripts_pool = pools.get("scripts")
        done = int(state.get("voiceovers_done", 0))
        for c in range(done, cycles):
            script_file = scripts_pool.next()
            if script_file is None:
                log.warning("Тексты закончились на цикле %d.", c)
                break
            text = _read_text(script_file)
            voice_id = voice_ids[c % len(voice_ids)]

            try:
                item = _voice_one(provider, text, voice_id, out_dir, c, char_limit)
                item["script"] = script_file.name
                results.append(item)
                scripts_pool.mark_consumed(script_file)
                state.update(voiceovers_done=c + 1)
                left = provider.tokens_left()
                if left is not None:
                    log.info("Остаток символов на аккаунте: %s", left)
                    if left <= 0:
                        log.warning("Токены аккаунта закончились — останавливаюсь.")
                        break
            except VoiceProviderError as exc:
                log.error("Цикл %d: озвучка не удалась: %s", c, exc)
                # Не роняем весь прогон — идём дальше.
                continue
    finally:
        provider.close()

    log.info("Готово озвучек: %d", len(results))
    return results


def _voice_one(provider: VoiceProvider, text: str, voice_id: str,
               out_dir: Path, index: int, char_limit: int) -> dict:
    chunks = split_text_for_tts(text, char_limit)
    if not chunks:
        raise VoiceProviderError("Пустой текст скрипта.")

    base = out_dir / f"vo_{index:04d}"
    if len(chunks) == 1:
        res = provider.tts(chunks[0], voice_id, base.with_suffix(".mp3"))
        _write_timings(base.with_suffix(".json"), text, res)
        return {"audio": str(res.audio_path), "duration": res.duration,
                "timings": str(base.with_suffix(".json"))}

    # Длинный текст: несколько кусков -> отдельные файлы + сдвиг таймингов.
    log.info("Текст длиннее лимита (%d симв.) — разбит на %d частей.",
             len(text), len(chunks))
    parts: list[TTSResult] = []
    offset = 0.0
    all_words = []
    for ci, chunk in enumerate(chunks):
        part_path = out_dir / f"vo_{index:04d}_p{ci}.mp3"
        res = provider.tts(chunk, voice_id, part_path)
        for w in res.words:
            all_words.append({"word": w.word, "start": w.start + offset,
                              "end": w.end + offset})
        offset += res.duration
        parts.append(res)
    _write_timings_raw(base.with_suffix(".json"), text, all_words, offset)
    return {"audio_parts": [str(p.audio_path) for p in parts],
            "duration": offset, "timings": str(base.with_suffix(".json"))}


def _write_timings(path: Path, text: str, res: TTSResult) -> None:
    data = {
        "text": text,
        "duration": res.duration,
        "words": [{"word": w.word, "start": w.start, "end": w.end}
                  for w in res.words],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def _write_timings_raw(path: Path, text: str, words: list[dict],
                       duration: float) -> None:
    data = {"text": text, "duration": duration, "words": words}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
