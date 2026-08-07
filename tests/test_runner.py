import csv

import pytest

from elevenlabs_voiceover import runner as runner_module
from elevenlabs_voiceover.api_client import ModelInfo, Subscription, TtsResult, VoicePreview
from elevenlabs_voiceover.chunker import Chunk
from elevenlabs_voiceover.config import MODE_ALL_VOICES, MODE_ROUND_ROBIN, Settings
from elevenlabs_voiceover.runner import (
    PreflightError,
    Runner,
    estimate_plan,
    list_txt_files,
    natural_key,
    read_text_file,
)
from elevenlabs_voiceover.state import StateStore

MP3 = b"\xff\xfb\x90\x00" + b"\x00" * 200


# ======================================================================
# Чтение файлов и сортировка
# ======================================================================
def test_reads_plain_utf8(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("Привет, мир", encoding="utf-8")
    assert read_text_file(path) == "Привет, мир"


def test_reads_utf8_with_bom(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("Привет", encoding="utf-8-sig")
    assert read_text_file(path) == "Привет"


def test_reads_windows_1251(tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes("Текст в кодировке Windows".encode("cp1251"))
    assert read_text_file(path) == "Текст в кодировке Windows"


def test_empty_file_returns_empty(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("   \n  ", encoding="utf-8")
    assert read_text_file(path) == ""


def test_natural_sort_orders_numbers_correctly():
    names = ["глава10.txt", "глава2.txt", "глава1.txt"]
    assert sorted(names, key=natural_key) == ["глава1.txt", "глава2.txt", "глава10.txt"]


def test_list_txt_files_ignores_other_extensions(tmp_path):
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    (tmp_path / "b.md").write_text("2", encoding="utf-8")
    (tmp_path / "c.TXT").write_text("3", encoding="utf-8")

    assert [p.name for p in list_txt_files(tmp_path)] == ["a.txt", "c.TXT"]


def test_list_txt_files_on_missing_directory(tmp_path):
    assert list_txt_files(tmp_path / "нет") == []


# ======================================================================
# Контекст на стыках
# ======================================================================
def test_previous_text_is_none_for_first_chunk():
    chunks = [Chunk(0, "первый"), Chunk(1, "второй")]
    assert Runner._previous_text(chunks, 0) is None


def test_previous_text_takes_tail():
    chunks = [Chunk(0, "а" * 1000), Chunk(1, "б")]
    assert Runner._previous_text(chunks, 1) == "а" * 600


def test_next_text_is_none_for_last_chunk():
    chunks = [Chunk(0, "первый"), Chunk(1, "второй")]
    assert Runner._next_text(chunks, 1) is None


def test_next_text_takes_head():
    chunks = [Chunk(0, "а"), Chunk(1, "б" * 1000)]
    assert Runner._next_text(chunks, 0) == "б" * 600


# ======================================================================
# Поддельный клиент
# ======================================================================
class FakeClient:
    def __init__(self, *, credits=1_000_000, limit=1_000_000, voice_limit=10, voice_slots_used=0):
        self.used = limit - credits
        self.limit = limit
        self.voice_limit = voice_limit
        self.voice_slots_used = voice_slots_used
        self.designs = []
        self.creates = []
        self.tts_calls = []
        self.deleted = []
        self.existing_voices = []
        self._counter = 0

    # -- служебное -----------------------------------------------------
    def get_subscription(self):
        return Subscription(
            tier="free",
            status="free",
            character_count=self.used,
            character_limit=self.limit,
            voice_slots_used=self.voice_slots_used,
            voice_limit=self.voice_limit,
            next_reset_unix=None,
            can_use_instant_voice_cloning=False,
            raw={},
        )

    def list_models(self):
        return [
            ModelInfo(
                model_id="eleven_flash_v2_5",
                name="Flash v2.5",
                can_do_text_to_speech=True,
                max_chars_per_request=40000,
                cost_multiplier=1.0,
                languages=["ru"],
            )
        ]

    def list_voices(self):
        return [{"voice_id": v} for v in self.existing_voices]

    # -- голоса --------------------------------------------------------
    def design_voice(self, description, **kwargs):
        self.designs.append(description)
        self.used += len(kwargs.get("preview_text") or "")
        return [
            VoicePreview(generated_voice_id=f"g{len(self.designs)}-{i}", audio=MP3,
                         duration_secs=2.0, language="ru")
            for i in range(3)
        ]

    def create_voice_from_preview(self, *, voice_name, voice_description, generated_voice_id, **kwargs):
        self.creates.append(voice_name)
        voice_id = f"voice-{len(self.creates)}"
        self.existing_voices.append(voice_id)
        self.voice_slots_used += 1
        return {"voice_id": voice_id, "name": voice_name}

    def delete_voice(self, voice_id):
        self.deleted.append(voice_id)
        if voice_id in self.existing_voices:
            self.existing_voices.remove(voice_id)
            self.voice_slots_used -= 1

    # -- озвучка -------------------------------------------------------
    def text_to_speech(self, voice_id, text, **kwargs):
        self.tts_calls.append((voice_id, text, kwargs))
        self.used += len(text)
        self._counter += 1
        return TtsResult(audio=MP3, request_id=f"req-{self._counter}", characters=len(text))

    def close(self):
        pass


@pytest.fixture
def workspace(tmp_path):
    prompts = tmp_path / "prompts"
    texts = tmp_path / "texts"
    output = tmp_path / "output"
    prompts.mkdir()
    texts.mkdir()
    return {"root": tmp_path, "prompts": prompts, "texts": texts, "output": output}


def write_prompts(folder, count=3):
    for i in range(1, count + 1):
        (folder / f"{i}-голос.txt").write_text(
            f"Голос номер {i}: спокойный, ровный, среднего тембра.", encoding="utf-8"
        )


def write_texts(folder, count=5, body="Короткий текст для озвучки. "):
    for i in range(1, count + 1):
        (folder / f"текст{i}.txt").write_text(f"{body}Файл номер {i}.", encoding="utf-8")


def make_settings(workspace, **overrides):
    values = dict(
        api_key="sk_test_1234567890",
        prompts_dir=str(workspace["prompts"]),
        texts_dir=str(workspace["texts"]),
        output_dir=str(workspace["output"]),
        model_id="eleven_flash_v2_5",
        max_voices=3,
        voice_mode=MODE_ROUND_ROBIN,
        pause_between_requests=0.0,
        use_ffmpeg=False,
        chunk_target_chars=2500,
    )
    values.update(overrides)
    return Settings(**values)


def run_with(monkeypatch, settings, store, client):
    monkeypatch.setattr(runner_module, "ElevenLabsClient", lambda *a, **k: client)
    runner = Runner(settings, store)
    return runner.run()


@pytest.fixture
def store(tmp_path):
    instance = StateStore(tmp_path / "state.sqlite3")
    yield instance
    instance.close()


# ======================================================================
# Проверки перед запуском
# ======================================================================
def test_missing_prompts_directory(workspace, store):
    settings = make_settings(workspace, prompts_dir=str(workspace["root"] / "нет"))
    with pytest.raises(PreflightError, match="промптами"):
        Runner(settings, store).run()


def test_missing_api_key(workspace, store):
    write_prompts(workspace["prompts"])
    write_texts(workspace["texts"])
    settings = make_settings(workspace, api_key="")
    settings.api_key = ""
    with pytest.raises(PreflightError, match="ключ"):
        Runner(settings, store).run()


def test_empty_prompts_folder(workspace, store):
    write_texts(workspace["texts"])
    settings = make_settings(workspace)
    with pytest.raises(PreflightError, match="нет ни одного"):
        Runner(settings, store).run()


def test_unavailable_model_is_reported(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"])
    write_texts(workspace["texts"])
    settings = make_settings(workspace, model_id="несуществующая_модель")

    with pytest.raises(PreflightError, match="недоступна"):
        run_with(monkeypatch, settings, store, FakeClient())


def test_no_credits_stops_before_start(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"])
    write_texts(workspace["texts"])
    settings = make_settings(workspace)

    with pytest.raises(PreflightError, match="кредит"):
        run_with(monkeypatch, settings, store, FakeClient(credits=0))


# ======================================================================
# Основной сценарий
# ======================================================================
def test_round_robin_assigns_voices_in_turn(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 3)
    write_texts(workspace["texts"], 5)
    client = FakeClient()

    stats = run_with(monkeypatch, make_settings(workspace), store, client)

    assert stats.voices_created == 3
    assert stats.texts_done == 5
    assert len(client.tts_calls) == 5

    used_voices = [call[0] for call in client.tts_calls]
    assert used_voices == ["voice-1", "voice-2", "voice-3", "voice-1", "voice-2"]


def test_output_files_are_written(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 3)
    write_texts(workspace["texts"], 4)

    run_with(monkeypatch, make_settings(workspace), store, FakeClient())

    produced = sorted(p.name for p in workspace["output"].glob("*.mp3"))
    assert produced == ["текст1.mp3", "текст2.mp3", "текст3.mp3", "текст4.mp3"]


def test_voice_previews_are_saved(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 2)
    write_texts(workspace["texts"], 1)

    run_with(monkeypatch, make_settings(workspace, max_voices=2), store, FakeClient())

    previews = list((workspace["output"] / "_voices").rglob("variant_*.mp3"))
    assert len(previews) == 6  # два голоса по три варианта


def test_manifest_records_voice_per_file(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 2)
    write_texts(workspace["texts"], 3)

    run_with(monkeypatch, make_settings(workspace, max_voices=2), store, FakeClient())

    manifest = workspace["output"] / "_manifest.csv"
    with manifest.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=";"))

    assert rows[0][0] == "Файл результата"
    assert [row[2] for row in rows[1:]] == ["1-голос", "2-голос", "1-голос"]


def test_all_voices_mode_multiplies_output(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 2)
    write_texts(workspace["texts"], 3)
    client = FakeClient()

    stats = run_with(
        monkeypatch, make_settings(workspace, max_voices=2, voice_mode=MODE_ALL_VOICES), store, client
    )

    assert stats.texts_done == 6
    assert len(list(workspace["output"].glob("*.mp3"))) == 6
    assert len(client.tts_calls) == 6


def test_max_voices_limits_prompts_used(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 5)
    write_texts(workspace["texts"], 2)
    client = FakeClient()

    run_with(monkeypatch, make_settings(workspace, max_voices=2), store, client)
    assert len(client.creates) == 2


def test_long_text_is_split_and_joined(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    (workspace["texts"] / "длинный.txt").write_text(
        " ".join(f"Предложение номер {i} для проверки нарезки." for i in range(200)),
        encoding="utf-8",
    )
    client = FakeClient()

    stats = run_with(
        monkeypatch, make_settings(workspace, max_voices=1, chunk_target_chars=300), store, client
    )

    assert len(client.tts_calls) > 1
    assert stats.chunks_done == len(client.tts_calls)
    assert (workspace["output"] / "длинный.mp3").exists()
    # Склейка сложила все куски в один файл.
    assert (workspace["output"] / "длинный.mp3").stat().st_size >= len(MP3) * 2


def test_chunk_context_is_passed(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    (workspace["texts"] / "длинный.txt").write_text(
        " ".join(f"Предложение номер {i} для проверки." for i in range(100)), encoding="utf-8"
    )
    client = FakeClient()

    run_with(monkeypatch, make_settings(workspace, max_voices=1, chunk_target_chars=300), store, client)

    first_kwargs = client.tts_calls[0][2]
    second_kwargs = client.tts_calls[1][2]
    assert first_kwargs["previous_text"] is None
    assert first_kwargs["next_text"]
    assert second_kwargs["previous_text"]
    assert second_kwargs["previous_request_ids"] == ["req-1"]


def test_temporary_chunks_are_removed(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    (workspace["texts"] / "длинный.txt").write_text(
        " ".join(f"Фраза {i} для нарезки текста." for i in range(100)), encoding="utf-8"
    )

    run_with(monkeypatch, make_settings(workspace, max_voices=1, chunk_target_chars=300), store, FakeClient())
    assert not (workspace["output"] / "_chunks").exists()


def test_chunks_are_kept_when_requested(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    (workspace["texts"] / "длинный.txt").write_text(
        " ".join(f"Фраза {i} для нарезки текста." for i in range(100)), encoding="utf-8"
    )

    run_with(
        monkeypatch,
        make_settings(workspace, max_voices=1, chunk_target_chars=300, keep_chunks=True),
        store,
        FakeClient(),
    )
    assert list((workspace["output"] / "_chunks").rglob("chunk_*.mp3"))


# ======================================================================
# Повторный запуск и продолжение
# ======================================================================
def test_second_run_skips_finished_texts(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 2)
    write_texts(workspace["texts"], 3)
    settings = make_settings(workspace, max_voices=2)

    run_with(monkeypatch, settings, store, FakeClient())

    second = FakeClient()
    stats = run_with(monkeypatch, settings, store, second)

    assert stats.texts_skipped == 3
    assert stats.texts_done == 0
    assert second.tts_calls == []


def test_second_run_reuses_voices(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 2)
    write_texts(workspace["texts"], 2)
    settings = make_settings(workspace, max_voices=2)

    first = FakeClient()
    run_with(monkeypatch, settings, store, first)

    second = FakeClient()
    second.existing_voices = list(first.existing_voices)
    stats = run_with(monkeypatch, settings, store, second)

    assert stats.voices_reused == 2
    assert second.designs == []


def test_voice_is_recreated_when_deleted_on_site(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 1)
    settings = make_settings(workspace, max_voices=1)

    run_with(monkeypatch, settings, store, FakeClient())

    # Второй прогон: в аккаунте голоса больше нет.
    second = FakeClient()
    second.existing_voices = []
    stats = run_with(monkeypatch, settings, store, second)

    assert stats.voices_created == 1
    assert len(second.designs) == 1


def test_recreate_flag_deletes_old_voice(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 1)
    settings = make_settings(workspace, max_voices=1)

    first = FakeClient()
    run_with(monkeypatch, settings, store, first)

    second = FakeClient()
    second.existing_voices = list(first.existing_voices)
    run_with(monkeypatch, make_settings(workspace, max_voices=1, recreate_voices=True), store, second)

    assert second.deleted == ["voice-1"]
    assert len(second.designs) == 1


def test_changing_settings_forces_regeneration(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 1)

    first = FakeClient()
    run_with(monkeypatch, make_settings(workspace, max_voices=1), store, first)

    # Другая скорость речи — прежний результат больше не подходит.
    second = FakeClient()
    second.existing_voices = list(first.existing_voices)
    stats = run_with(monkeypatch, make_settings(workspace, max_voices=1, speed=1.3), store, second)

    assert stats.texts_done == 1
    assert len(second.tts_calls) == 1


# ======================================================================
# Бюджет
# ======================================================================
def test_run_stops_when_credits_run_out(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 20, body="Довольно длинный текст для озвучки. " * 5)

    # Хватит на создание голоса и пару текстов, не больше.
    client = FakeClient(credits=1000, limit=10000)
    stats = run_with(monkeypatch, make_settings(workspace, max_voices=1), store, client)

    assert stats.stopped_reason
    assert 0 < stats.texts_done < 20


def test_reserve_is_not_spent(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 10, body="Текст для озвучки. " * 10)

    client = FakeClient(credits=5000, limit=10000)
    settings = make_settings(workspace, max_voices=1, reserve_credits=4500)
    stats = run_with(monkeypatch, settings, store, client)

    assert stats.credits_estimated <= 500


def test_finished_work_is_resumable_after_quota_stop(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 10, body="Текст для проверки продолжения. " * 3)

    limited = FakeClient(credits=800, limit=10000)
    first = run_with(monkeypatch, make_settings(workspace, max_voices=1), store, limited)
    assert first.texts_done >= 1

    generous = FakeClient(credits=1_000_000)
    generous.existing_voices = list(limited.existing_voices)
    second = run_with(monkeypatch, make_settings(workspace, max_voices=1), store, generous)

    assert second.texts_skipped == first.texts_done
    assert second.texts_done == 10 - first.texts_done


# ======================================================================
# Оценка без обращения к API
# ======================================================================
def test_estimate_counts_files_and_characters(workspace):
    write_prompts(workspace["prompts"], 3)
    write_texts(workspace["texts"], 4)

    plan = estimate_plan(make_settings(workspace))

    assert plan["prompts"] == 3
    assert plan["voices"] == 3
    assert plan["texts"] == 4
    assert plan["characters"] > 0
    assert plan["design_credits"] > 0


def test_estimate_accounts_for_all_voices_mode(workspace):
    write_prompts(workspace["prompts"], 2)
    write_texts(workspace["texts"], 3)

    single = estimate_plan(make_settings(workspace, max_voices=2))
    everyone = estimate_plan(make_settings(workspace, max_voices=2, voice_mode=MODE_ALL_VOICES))

    assert everyone["characters"] == single["characters"] * 2


def test_estimate_flash_is_half_of_multilingual(workspace):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 2)

    plan = estimate_plan(make_settings(workspace, max_voices=1))
    body = plan["total_credits_multilingual"] - plan["design_credits"]
    assert plan["total_credits_flash"] - plan["design_credits"] == pytest.approx(body / 2, abs=1)


def test_estimate_on_empty_folders(workspace):
    plan = estimate_plan(make_settings(workspace))
    assert plan["texts"] == 0
    assert plan["characters"] == 0
