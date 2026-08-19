"""Сквозная проверка на настоящем HTTP.

Поднимаем локальный сервер, повторяющий контракт ElevenLabs, и работаем через
обычный requests-клиент. Остальные тесты подменяют клиент целиком и потому не
проверяют ни заголовки, ни разбор JSON, ни приём двоичного ответа.
"""

from __future__ import annotations

import base64
import functools
import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

from elevenlabs_voiceover import runner as runner_module
from elevenlabs_voiceover.api_client import ElevenLabsClient
from elevenlabs_voiceover.config import Settings
from elevenlabs_voiceover.runner import Runner
from elevenlabs_voiceover.state import StateStore

API_KEY = "sk_e2e_test_key_0123456789"
CHARACTER_LIMIT = 100_000

# Один настоящий кадр MPEG1 Layer III: 128 кбит/с, 44100 Гц, стерео.
FRAME_LENGTH = 417
AUDIO_FRAME = bytes([0xFF, 0xFB, 0x90, 0x00]) + b"\x00" * (FRAME_LENGTH - 4)
FAKE_MP3 = AUDIO_FRAME * 8

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


class ServerState:
    def __init__(self) -> None:
        self.characters_used = 0
        self.voice_slots_used = 0
        self.tts_requests = 0
        self.designs = 0
        self.voices: dict = {}
        self.voices_ever = 0
        self.rejected_keys = 0
        self.lock = threading.Lock()


def make_handler(state: ServerState):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # тишина в выводе тестов
            pass

        # -- вспомогательное -------------------------------------------
        def _json(self, status, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorised(self) -> bool:
            if self.headers.get("xi-api-key") == API_KEY:
                return True
            with state.lock:
                state.rejected_keys += 1
            self._json(401, {"detail": {"status": "invalid_api_key", "message": "ключ неверен"}})
            return False

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}")

        # -- маршруты ---------------------------------------------------
        def do_GET(self):
            if not self._authorised():
                return
            path = urlparse(self.path).path

            if path == "/v1/user/subscription":
                with state.lock:
                    self._json(200, {
                        "tier": "free",
                        "status": "free",
                        "character_count": state.characters_used,
                        "character_limit": CHARACTER_LIMIT,
                        "voice_slots_used": state.voice_slots_used,
                        "voice_limit": 10,
                        "next_character_count_reset_unix": 1800000000,
                        "can_use_instant_voice_cloning": False,
                    })
            elif path == "/v1/models":
                self._json(200, [{
                    "model_id": "eleven_flash_v2_5",
                    "name": "Flash v2.5",
                    "can_do_text_to_speech": True,
                    "maximum_text_length_per_request": 40000,
                    "model_rates": {"character_cost_multiplier": 1.0, "cost_discount_multiplier": 0.5},
                    "languages": [{"language_id": "ru", "name": "Russian"}],
                }])
            elif path == "/v1/voices":
                with state.lock:
                    self._json(200, {"voices": [{"voice_id": v} for v in state.voices]})
            else:
                self._json(404, {"detail": "нет такого пути"})

        def do_POST(self):
            if not self._authorised():
                return
            path = urlparse(self.path).path
            body = self._body()

            if path == "/v1/text-to-voice/design":
                preview = body.get("text") or ""
                with state.lock:
                    state.designs += 1
                    state.characters_used += len(preview)
                    index = state.designs
                encoded = base64.b64encode(FAKE_MP3).decode()
                self._json(200, {
                    "previews": [
                        {"audio_base_64": encoded, "generated_voice_id": f"gen-{index}-{i}",
                         "media_type": "audio/mpeg", "duration_secs": 1.0, "language": "ru"}
                        for i in range(3)
                    ],
                    "text": preview,
                })

            elif path == "/v1/text-to-voice":
                with state.lock:
                    # Счётчик, а не длина словаря: после удаления голоса
                    # идентификатор не должен выдаваться повторно.
                    state.voices_ever += 1
                    voice_id = f"voice-{state.voices_ever}"
                    state.voices[voice_id] = body.get("voice_name")
                    state.voice_slots_used += 1
                self._json(200, {"voice_id": voice_id, "name": body.get("voice_name")})

            elif path.startswith("/v1/text-to-speech/"):
                voice_id = path.rsplit("/", 1)[-1]
                if voice_id not in state.voices:
                    self._json(422, {"detail": [
                        {"loc": ["path", "voice_id"], "msg": "нет такого голоса", "type": "value_error"}
                    ]})
                    return
                text = body.get("text") or ""
                with state.lock:
                    if state.characters_used + len(text) > CHARACTER_LIMIT:
                        self._json(401, {"detail": {"status": "quota_exceeded", "message": "кредиты кончились"}})
                        return
                    state.characters_used += len(text)
                    state.tts_requests += 1
                    number = state.tts_requests
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Content-Length", str(len(FAKE_MP3)))
                self.send_header("request-id", f"req-{number}")
                self.end_headers()
                self.wfile.write(FAKE_MP3)

            else:
                self._json(404, {"detail": "нет такого пути"})

        def do_DELETE(self):
            if not self._authorised():
                return
            voice_id = urlparse(self.path).path.rsplit("/", 1)[-1]
            with state.lock:
                state.voices.pop(voice_id, None)
                state.voice_slots_used = max(0, state.voice_slots_used - 1)
            self._json(200, {"status": "ok"})

    return Handler


@pytest.fixture
def api(monkeypatch):
    """Локальный сервер плюс перенаправленный на него настоящий клиент."""
    state = ServerState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"

    monkeypatch.setattr(
        runner_module, "ElevenLabsClient", functools.partial(ElevenLabsClient, base_url=base_url)
    )
    state.base_url = base_url
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


# ----------------------------------------------------------------------
def build_workspace(root: Path, *, prompts: int = 3, texts: int = 4, sentences: int = 1) -> Path:
    for name in ("prompts", "texts"):
        (root / name).mkdir(parents=True, exist_ok=True)
    for i in range(1, prompts + 1):
        (root / "prompts" / f"{i}-голос.txt").write_text(
            f"Native Russian. Голос {i}, спокойный и ровный.", encoding="utf-8"
        )
    for i in range(1, texts + 1):
        body = " ".join(
            f"Это предложение номер {j} из текста {i}, нужное для проверки нарезки."
            for j in range(sentences)
        )
        (root / "texts" / f"текст{i}.txt").write_text(body, encoding="utf-8")
    return root


def settings_for(root: Path, **extra) -> Settings:
    values = dict(
        api_key=API_KEY,
        prompts_dir=str(root / "prompts"),
        texts_dir=str(root / "texts"),
        output_dir=str(root / "out"),
        model_id="eleven_flash_v2_5",
        max_voices=3,
        pause_between_requests=0.0,
        chunk_target_chars=2500,
    )
    values.update(extra)
    return Settings(**values)


def run(root: Path, db: Path, **extra):
    store = StateStore(db)
    try:
        return Runner(settings_for(root, **extra), store).run()
    finally:
        store.close()


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


# ======================================================================
def test_full_run_over_http(api, tmp_path):
    root = build_workspace(tmp_path / "work", prompts=3, texts=4)
    stats = run(root, tmp_path / "state.sqlite3")

    assert stats.voices_created == 3
    assert stats.texts_done == 4
    assert stats.failures == []
    assert api.tts_requests == 4
    assert api.rejected_keys == 0

    produced = sorted(p.name for p in (root / "out").glob("*.mp3"))
    assert produced == ["текст1.mp3", "текст2.mp3", "текст3.mp3", "текст4.mp3"]


def test_voices_rotate_over_http(api, tmp_path):
    root = build_workspace(tmp_path / "work", prompts=3, texts=4)
    run(root, tmp_path / "state.sqlite3")

    manifest = (root / "out" / "_manifest.csv").read_text(encoding="utf-8-sig")
    voices = [line.split(";")[2] for line in manifest.strip().splitlines()[1:]]
    assert voices == ["1-голос", "2-голос", "3-голос", "1-голос"]


def test_previews_are_saved_over_http(api, tmp_path):
    root = build_workspace(tmp_path / "work", prompts=2, texts=1)
    run(root, tmp_path / "state.sqlite3", max_voices=2)

    assert len(list((root / "out" / "_voices").rglob("variant_*.mp3"))) == 6


def test_long_text_is_split_and_joined_over_http(api, tmp_path):
    root = build_workspace(tmp_path / "work", prompts=1, texts=1, sentences=60)
    # Без ffmpeg, чтобы размер результата был предсказуем до байта: ffmpeg
    # дописывает к склейке собственный служебный заголовок.
    run(root, tmp_path / "state.sqlite3", max_voices=1, chunk_target_chars=400, use_ffmpeg=False)

    assert api.tts_requests > 3
    result = root / "out" / "текст1.mp3"
    assert result.exists()
    assert result.stat().st_size == len(FAKE_MP3) * api.tts_requests


def test_second_run_spends_nothing(api, tmp_path):
    root = build_workspace(tmp_path / "work", prompts=2, texts=3)
    db = tmp_path / "state.sqlite3"

    run(root, db, max_voices=2)
    spent = api.tts_requests
    designs = api.designs

    stats = run(root, db, max_voices=2)

    assert stats.texts_skipped == 3
    assert stats.voices_reused == 2
    assert api.tts_requests == spent
    assert api.designs == designs


def test_wrong_key_stops_immediately(api, tmp_path):
    root = build_workspace(tmp_path / "work", prompts=1, texts=2)
    stats = run(root, tmp_path / "state.sqlite3", api_key="sk_wrong_key_00000000")

    assert stats.texts_done == 0
    assert "ключ" in stats.stopped_reason.lower()
    assert api.rejected_keys > 0
    assert api.tts_requests == 0


def test_run_stops_on_quota_and_resumes(api, tmp_path):
    root = build_workspace(tmp_path / "work", prompts=1, texts=8, sentences=8)
    db = tmp_path / "state.sqlite3"

    # Оставляем на балансе ровно столько, чтобы хватило на пару текстов.
    reserve = CHARACTER_LIMIT - 1200
    first = run(root, db, max_voices=1, reserve_credits=reserve)

    assert first.stopped_reason
    assert 0 < first.texts_done < 8

    # Манифест должен появиться и после аварийной остановки.
    manifest = (root / "out" / "_manifest.csv").read_text(encoding="utf-8-sig")
    rows = [line.split(";") for line in manifest.strip().splitlines()]
    ready_column = rows[0].index("Готов")
    ready = [row[ready_column] for row in rows[1:]]

    assert ready.count("да") == first.texts_done
    assert ready.count("нет") == 8 - first.texts_done

    second = run(root, db, max_voices=1, reserve_credits=0)

    assert second.texts_skipped == first.texts_done
    assert second.texts_done == 8 - first.texts_done
    assert len(list((root / "out").glob("*.mp3"))) == 8


def test_recreate_deletes_voice_over_http(api, tmp_path):
    root = build_workspace(tmp_path / "work", prompts=1, texts=1)
    db = tmp_path / "state.sqlite3"

    run(root, db, max_voices=1)
    assert list(api.voices) == ["voice-1"]

    run(root, db, max_voices=1, recreate_voices=True)
    assert "voice-1" not in api.voices
    assert list(api.voices) == ["voice-2"]


@pytest.mark.skipif(not HAS_FFMPEG, reason="нужен ffmpeg для проверки длительности")
def test_joined_file_decodes_cleanly(api, tmp_path):
    root = build_workspace(tmp_path / "work", prompts=1, texts=1, sentences=60)
    run(root, tmp_path / "state.sqlite3", max_voices=1, chunk_target_chars=400, use_ffmpeg=False)

    result = root / "out" / "текст1.mp3"
    decoded = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(result), "-f", "null", "-"],
        capture_output=True, text=True,
    )
    assert decoded.returncode == 0
    assert not decoded.stderr.strip()

    # 8 кадров по 1152 отсчёта на 44100 Гц в каждом ответе сервера.
    expected = api.tts_requests * 8 * 1152 / 44100
    assert abs(duration(result) - expected) < 0.2
