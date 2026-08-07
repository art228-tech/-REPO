import pytest

from elevenlabs_voiceover.state import StateStore, StoredVoice, digest


@pytest.fixture
def store(tmp_path):
    instance = StateStore(tmp_path / "state.sqlite3")
    yield instance
    instance.close()


def voice(prompt_key="k1", voice_id="v1", name="Диктор") -> StoredVoice:
    return StoredVoice(
        prompt_key=prompt_key,
        prompt_file="1-диктор.txt",
        voice_id=voice_id,
        voice_name=name,
        description="Мужской голос, спокойный",
    )


# ----------------------------------------------------------------------
def test_digest_is_stable():
    assert digest("a", 1) == digest("a", 1)


def test_digest_separates_fields():
    # Без разделителя ("ab", "c") и ("a", "bc") дали бы одинаковый хеш.
    assert digest("ab", "c") != digest("a", "bc")


def test_unknown_voice_is_none(store):
    assert store.get_voice("нет-такого") is None


def test_voice_round_trip(store):
    store.save_voice(voice())
    loaded = store.get_voice("k1")
    assert loaded is not None
    assert loaded.voice_id == "v1"
    assert loaded.voice_name == "Диктор"


def test_saving_same_key_updates(store):
    store.save_voice(voice())
    store.save_voice(voice(voice_id="v2", name="Другой"))
    loaded = store.get_voice("k1")
    assert loaded.voice_id == "v2"
    assert len(store.all_voices()) == 1


def test_forget_voice(store):
    store.save_voice(voice())
    store.forget_voice("k1")
    assert store.get_voice("k1") is None


def test_all_voices_lists_everything(store):
    store.save_voice(voice("k1", "v1"))
    store.save_voice(voice("k2", "v2"))
    assert {v.voice_id for v in store.all_voices()} == {"v1", "v2"}


# ----------------------------------------------------------------------
def test_chunk_done_requires_existing_file(store, tmp_path):
    audio = tmp_path / "chunk.mp3"
    audio.write_bytes(b"x")

    store.mark_chunk_done(
        "t1", text_file="глава1", voice_id="v1", chunk_index=0,
        characters=100, audio_path=str(audio), request_id="req-1",
    )
    assert store.chunk_is_done("t1") == str(audio)


def test_chunk_is_not_done_when_file_deleted(store, tmp_path):
    audio = tmp_path / "chunk.mp3"
    audio.write_bytes(b"x")
    store.mark_chunk_done(
        "t1", text_file="глава1", voice_id="v1", chunk_index=0,
        characters=100, audio_path=str(audio), request_id=None,
    )
    audio.unlink()
    assert store.chunk_is_done("t1") is None


def test_failed_chunk_is_not_done(store):
    store.mark_chunk_failed(
        "t1", text_file="глава1", voice_id="v1", chunk_index=0,
        characters=100, error="что-то пошло не так",
    )
    assert store.chunk_is_done("t1") is None


def test_chunk_can_recover_after_failure(store, tmp_path):
    store.mark_chunk_failed(
        "t1", text_file="глава1", voice_id="v1", chunk_index=0,
        characters=100, error="сеть отвалилась",
    )
    audio = tmp_path / "chunk.mp3"
    audio.write_bytes(b"x")
    store.mark_chunk_done(
        "t1", text_file="глава1", voice_id="v1", chunk_index=0,
        characters=100, audio_path=str(audio), request_id="req-2",
    )
    assert store.chunk_is_done("t1") == str(audio)
    assert store.get_chunk_request_id("t1") == "req-2"


def test_request_id_is_stored(store, tmp_path):
    audio = tmp_path / "c.mp3"
    audio.write_bytes(b"x")
    store.mark_chunk_done(
        "t1", text_file="г", voice_id="v", chunk_index=0,
        characters=1, audio_path=str(audio), request_id="req-abc",
    )
    assert store.get_chunk_request_id("t1") == "req-abc"


# ----------------------------------------------------------------------
def test_output_requires_existing_file(store, tmp_path):
    result = tmp_path / "готово.mp3"
    result.write_bytes(b"x")
    store.mark_output_done(
        "o1", text_file="глава1", voice_id="v1", voice_name="Диктор",
        output_path=str(result), characters=500,
    )
    assert store.output_is_done("o1") == str(result)

    result.unlink()
    assert store.output_is_done("o1") is None


def test_unknown_output_is_none(store):
    assert store.output_is_done("нет") is None


# ----------------------------------------------------------------------
def test_reset_keeps_voices_by_default(store, tmp_path):
    audio = tmp_path / "c.mp3"
    audio.write_bytes(b"x")
    store.save_voice(voice())
    store.mark_chunk_done(
        "t1", text_file="г", voice_id="v1", chunk_index=0,
        characters=1, audio_path=str(audio), request_id=None,
    )

    store.reset_progress()
    assert store.chunk_is_done("t1") is None
    assert store.get_voice("k1") is not None


def test_reset_can_drop_voices(store):
    store.save_voice(voice())
    store.reset_progress(drop_voices=True)
    assert store.get_voice("k1") is None


# ----------------------------------------------------------------------
def test_usage_and_summary(store):
    store.log_usage("tts", 1500, "v1", "глава1")
    store.log_usage("voice_design", 200, note="диктор")

    summary = store.summary()
    assert summary["characters_spent"] == 1700
    assert summary["voices"] == 0


def test_run_lifecycle_is_recorded(store):
    run_id = store.start_run()
    store.finish_run(run_id, "ok", {"texts_done": 3})

    summary = store.summary()
    assert summary["recent_runs"][0]["outcome"] == "ok"


def test_summary_reports_failures(store):
    store.mark_chunk_failed(
        "t1", text_file="глава1", voice_id="v1", chunk_index=2,
        characters=10, error="422 отклонено",
    )
    summary = store.summary()
    assert summary["chunks_failed"] == 1
    assert summary["recent_errors"][0]["text_file"] == "глава1"
