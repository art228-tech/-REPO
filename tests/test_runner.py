import csv

import pytest

from elevenlabs_voiceover import runner as runner_module
from elevenlabs_voiceover.api_client import ModelInfo, Subscription, TtsResult, VoicePreview
from elevenlabs_voiceover.chunker import Chunk
from elevenlabs_voiceover.config import (
    DONE_DELETE,
    DONE_FOLDER_NAME,
    DONE_MOVE,
    MODE_ALL_VOICES,
    MODE_ROUND_ROBIN,
    SOURCE_ACCOUNT,
    Settings,
)
from elevenlabs_voiceover.runner import (
    PreflightError,
    Runner,
    count_txt_files,
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


def test_count_txt_files_matches_list(tmp_path):
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    (tmp_path / "b.md").write_text("2", encoding="utf-8")
    (tmp_path / "c.TXT").write_text("3", encoding="utf-8")
    (tmp_path / "подпапка").mkdir()
    (tmp_path / "подпапка" / "внутри.txt").write_text("4", encoding="utf-8")

    assert count_txt_files(tmp_path) == 2
    assert count_txt_files(tmp_path / "нет") == 0


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
        self.account_catalog = []
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
        if self.account_catalog:
            return [
                {"voice_id": vid, "name": name, "category": category}
                for vid, name, category in self.account_catalog
            ]
        return [{"voice_id": v} for v in self.existing_voices]

    def account_voices(self):
        from elevenlabs_voiceover.api_client import AccountVoice

        voices = [
            AccountVoice(
                voice_id=str(item["voice_id"]),
                name=str(item.get("name") or item["voice_id"]),
                category=str(item.get("category") or ""),
            )
            for item in self.list_voices()
        ]
        return sorted(voices, key=lambda v: (not v.is_custom, v.name.lower()))

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


def test_line_breaks_reach_the_api_by_default(workspace, store, monkeypatch):
    """Переносы дают паузу, и по умолчанию мы их сохраняем."""
    write_prompts(workspace["prompts"], 1)
    (workspace["texts"] / "речь.txt").write_text("Раз.\nДва.\nТри.", encoding="utf-8")
    client = FakeClient()

    run_with(monkeypatch, make_settings(workspace, max_voices=1), store, client)

    assert client.tts_calls[0][1] == "Раз.\nДва.\nТри."


def test_line_breaks_can_be_removed(workspace, store, monkeypatch):
    from elevenlabs_voiceover.chunker import LINE_BREAKS_SOFT

    write_prompts(workspace["prompts"], 1)
    (workspace["texts"] / "речь.txt").write_text("Раз.\nДва.\nТри.", encoding="utf-8")
    client = FakeClient()

    settings = make_settings(workspace, max_voices=1, line_breaks=LINE_BREAKS_SOFT)
    run_with(monkeypatch, settings, store, client)

    assert client.tts_calls[0][1] == "Раз. Два. Три."


def test_estimate_does_not_read_text_files(workspace, monkeypatch):
    """Выбор папки текстов не должен открывать файлы — в ней их может быть очень много."""
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 3)

    def boom(path):
        raise AssertionError(f"оценке незачем читать {path}")

    monkeypatch.setattr(runner_module, "read_text_file", boom)
    plan = estimate_plan(make_settings(workspace, max_voices=1))
    assert plan["texts"] == 3
    assert plan["characters"] == 0
    assert plan["line_breaks"] == 0


def test_run_does_not_read_texts_before_client_starts(workspace, store, monkeypatch):
    """Старт не должен открывать все txt сразу — иначе на большой папке всё зависает."""
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 8)
    text_names = {path.name for path in workspace["texts"].glob("*.txt")}

    reads: list = []
    original = runner_module.read_text_file

    def tracking(path):
        reads.append(path.name)
        return original(path)

    texts_seen_when_client_created = []

    def factory(*_args, **_kwargs):
        texts_seen_when_client_created.append([name for name in reads if name in text_names])
        return FakeClient()

    monkeypatch.setattr(runner_module, "read_text_file", tracking)
    monkeypatch.setattr(runner_module, "ElevenLabsClient", factory)

    stats = Runner(make_settings(workspace, max_voices=1), store).run()

    assert texts_seen_when_client_created == [[]]
    assert stats.texts_done == 8
    assert text_names <= set(reads)


def test_empty_text_is_skipped_without_blocking_others(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 2)
    (workspace["texts"] / "пустой.txt").write_text("   \n", encoding="utf-8")

    stats = run_with(monkeypatch, make_settings(workspace, max_voices=1), store, FakeClient())

    assert stats.texts_done == 2
    assert stats.texts_total == 3


def test_manifest_records_pace(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 2)

    run_with(monkeypatch, make_settings(workspace, max_voices=1), store, FakeClient())

    manifest = (workspace["output"] / "_manifest.csv").read_text(encoding="utf-8-sig")
    rows = [line.split(";") for line in manifest.strip().splitlines()]
    column = rows[0].index("Символов в секунду")

    assert all(row[column] for row in rows[1:])


def test_manifest_records_duration(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 2)

    stats = run_with(monkeypatch, make_settings(workspace, max_voices=1), store, FakeClient())

    manifest = (workspace["output"] / "_manifest.csv").read_text(encoding="utf-8-sig")
    rows = [line.split(";") for line in manifest.strip().splitlines()]
    column = rows[0].index("Длительность")

    # Поддельный клиент отдаёт настоящие кадры MPEG, длительность измерима.
    assert all(row[column] for row in rows[1:])
    assert stats.seconds_produced > 0


def test_duration_is_reported_in_stats(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 3)

    stats = run_with(monkeypatch, make_settings(workspace, max_voices=1), store, FakeClient())

    assert "audio_duration" in stats.as_dict()
    assert stats.as_dict()["audio_duration"]


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


def test_changing_settings_does_not_overwrite_existing_file(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 1)

    first = FakeClient()
    run_with(monkeypatch, make_settings(workspace, max_voices=1), store, first)
    produced = list(workspace["output"].glob("*.mp3"))
    assert produced
    original = produced[0].read_bytes()

    second = FakeClient()
    second.existing_voices = list(first.existing_voices)
    stats = run_with(monkeypatch, make_settings(workspace, max_voices=1, speed=1.3), store, second)

    assert stats.texts_skipped == 1
    assert second.tts_calls == []
    assert produced[0].read_bytes() == original


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
def test_estimate_counts_files_without_reading_them(workspace):
    write_prompts(workspace["prompts"], 3)
    write_texts(workspace["texts"], 4)

    plan = estimate_plan(make_settings(workspace))

    assert plan["prompts"] == 3
    assert plan["voices"] == 3
    assert plan["texts"] == 4
    assert plan["characters"] == 0
    assert plan["design_credits"] > 0


def test_estimate_counts_output_files(workspace):
    """Число файлов на выходе — то, что человек и хочет увидеть до запуска."""
    write_prompts(workspace["prompts"], 3)
    write_texts(workspace["texts"], 10)

    one_each = estimate_plan(make_settings(workspace, max_voices=3))
    assert one_each["texts"] == 10
    assert one_each["outputs"] == 10

    every_voice = estimate_plan(make_settings(workspace, max_voices=3, voice_mode=MODE_ALL_VOICES))
    assert every_voice["texts"] == 10
    assert every_voice["outputs"] == 30


def test_estimate_accounts_for_all_voices_mode(workspace):
    write_prompts(workspace["prompts"], 2)
    write_texts(workspace["texts"], 3)

    single = estimate_plan(make_settings(workspace, max_voices=2))
    everyone = estimate_plan(make_settings(workspace, max_voices=2, voice_mode=MODE_ALL_VOICES))

    assert single["outputs"] == 3
    assert everyone["outputs"] == 6


def test_source_texts_stay_by_default(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 3)

    run_with(monkeypatch, make_settings(workspace, max_voices=1), store, FakeClient())

    assert len(list(workspace["texts"].glob("*.txt"))) == 3


def test_source_texts_are_deleted_when_asked(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 3)

    settings = make_settings(workspace, max_voices=1, done_action=DONE_DELETE)
    stats = run_with(monkeypatch, settings, store, FakeClient())

    assert stats.texts_done == 3
    assert list(workspace["texts"].glob("*.txt")) == []
    # Результаты при этом на месте.
    assert len(list(workspace["output"].glob("*.mp3"))) == 3


def test_source_texts_are_moved_when_asked(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 2)

    settings = make_settings(workspace, max_voices=1, done_action=DONE_MOVE)
    run_with(monkeypatch, settings, store, FakeClient())

    assert list(workspace["texts"].glob("*.txt")) == []
    moved = sorted(p.name for p in (workspace["texts"] / DONE_FOLDER_NAME).glob("*.txt"))
    assert moved == ["текст1.txt", "текст2.txt"]


def test_moved_texts_are_not_picked_up_again(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 2)
    settings = make_settings(workspace, max_voices=1, done_action=DONE_MOVE)

    run_with(monkeypatch, settings, store, FakeClient())

    second = FakeClient()
    second.existing_voices = ["voice-1"]
    with pytest.raises(PreflightError, match="нет ни одного"):
        run_with(monkeypatch, settings, store, second)


def test_move_does_not_overwrite_existing_file(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 1)
    done = workspace["texts"] / DONE_FOLDER_NAME
    done.mkdir()
    (done / "текст1.txt").write_text("прошлый прогон", encoding="utf-8")

    settings = make_settings(workspace, max_voices=1, done_action=DONE_MOVE)
    run_with(monkeypatch, settings, store, FakeClient())

    assert (done / "текст1.txt").read_text(encoding="utf-8") == "прошлый прогон"
    assert (done / "текст1_2.txt").exists()


def test_source_survives_failed_voiceover(workspace, store, monkeypatch):
    """Текст нельзя трогать, если озвучка не получилась."""
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 2)

    client = FakeClient(credits=1, limit=10000)
    settings = make_settings(workspace, max_voices=1, done_action=DONE_DELETE)
    run_with(monkeypatch, settings, store, client)

    # Кредитов не хватило даже на первый текст — исходники должны остаться.
    assert len(list(workspace["texts"].glob("*.txt"))) == 2


def test_source_removed_only_after_all_voices(workspace, store, monkeypatch):
    """В режиме «всеми голосами» текст нужен до последней озвучки."""
    write_prompts(workspace["prompts"], 3)
    write_texts(workspace["texts"], 1)

    settings = make_settings(
        workspace, max_voices=3, voice_mode=MODE_ALL_VOICES, done_action=DONE_DELETE
    )
    stats = run_with(monkeypatch, settings, store, FakeClient())

    assert stats.texts_done == 3
    assert list(workspace["texts"].glob("*.txt")) == []
    assert len(list(workspace["output"].glob("*.mp3"))) == 3


def test_delete_works_together_with_saving_beside(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 2)

    settings = make_settings(
        workspace, max_voices=1, save_next_to_texts=True, done_action=DONE_DELETE, output_dir=""
    )
    run_with(monkeypatch, settings, store, FakeClient())

    assert list(workspace["texts"].glob("*.txt")) == []
    assert sorted(p.name for p in workspace["texts"].glob("*.mp3")) == ["текст1.mp3", "текст2.mp3"]


def test_broken_done_action_falls_back_to_keeping(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 1)

    settings = make_settings(workspace, max_voices=1, done_action="что-то своё")
    assert settings.done_action == "keep"

    run_with(monkeypatch, settings, store, FakeClient())
    assert len(list(workspace["texts"].glob("*.txt"))) == 1


def test_result_lands_next_to_source_text(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 3)

    settings = make_settings(workspace, max_voices=1, save_next_to_texts=True)
    stats = run_with(monkeypatch, settings, store, FakeClient())

    assert stats.texts_done == 3
    produced = sorted(p.name for p in workspace["texts"].glob("*.mp3"))
    assert produced == ["текст1.mp3", "текст2.mp3", "текст3.mp3"]
    # Отдельная папка результатов не задействована.
    assert list(workspace["output"].glob("*.mp3")) == []


def test_name_matches_source_exactly(workspace, store, monkeypatch):
    """Имя должно совпадать с исходным символ в символ, включая пробелы и точки."""
    write_prompts(workspace["prompts"], 1)
    tricky = "Глава 1. Начало — часть (первая)"
    (workspace["texts"] / f"{tricky}.txt").write_text("Короткий текст.", encoding="utf-8")

    settings = make_settings(workspace, max_voices=1, save_next_to_texts=True)
    run_with(monkeypatch, settings, store, FakeClient())

    assert (workspace["texts"] / f"{tricky}.mp3").exists()


def test_output_folder_not_required_when_saving_beside(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 1)

    settings = make_settings(workspace, max_voices=1, save_next_to_texts=True, output_dir="")
    stats = run_with(monkeypatch, settings, store, FakeClient())

    assert stats.texts_done == 1


def test_manifest_lands_with_the_texts(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 2)

    settings = make_settings(workspace, max_voices=1, save_next_to_texts=True, output_dir="")
    run_with(monkeypatch, settings, store, FakeClient())

    assert (workspace["texts"] / "_manifest.csv").exists()


def test_temporary_chunks_do_not_stay_with_the_texts(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    (workspace["texts"] / "длинный.txt").write_text(
        " ".join(f"Фраза {i} для нарезки текста." for i in range(100)), encoding="utf-8"
    )

    settings = make_settings(
        workspace, max_voices=1, chunk_target_chars=300, save_next_to_texts=True, output_dir=""
    )
    run_with(monkeypatch, settings, store, FakeClient())

    assert (workspace["texts"] / "длинный.mp3").exists()
    assert not (workspace["texts"] / "_chunks").exists()


def test_all_voices_mode_keeps_names_apart(workspace, store, monkeypatch):
    """Один текст всеми голосами: имена не должны столкнуться."""
    write_prompts(workspace["prompts"], 2)
    write_texts(workspace["texts"], 1)

    settings = make_settings(
        workspace, max_voices=2, voice_mode=MODE_ALL_VOICES,
        save_next_to_texts=True, output_dir="",
    )
    stats = run_with(monkeypatch, settings, store, FakeClient())

    assert stats.texts_done == 2
    produced = sorted(p.name for p in workspace["texts"].glob("*.mp3"))
    assert produced == ["текст1__1-голос.mp3", "текст1__2-голос.mp3"]


def test_second_run_beside_texts_skips_finished(workspace, store, monkeypatch):
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 2)
    settings = make_settings(workspace, max_voices=1, save_next_to_texts=True)

    run_with(monkeypatch, settings, store, FakeClient())

    second = FakeClient()
    second.existing_voices = ["voice-1"]
    stats = run_with(monkeypatch, settings, store, second)

    assert stats.texts_skipped == 2
    assert second.tts_calls == []


def test_existing_mp3_on_disk_is_not_replaced(workspace, store, monkeypatch):
    """Готовые mp3 нельзя затирать — надо озвучивать те, которых ещё нет."""
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 5)
    settings = make_settings(workspace, max_voices=1, save_next_to_texts=True)

    already = MP3 + b"KEEP"
    (workspace["texts"] / "текст1.mp3").write_bytes(already)
    (workspace["texts"] / "текст2.mp3").write_bytes(already)

    client = FakeClient()
    stats = run_with(monkeypatch, settings, store, client)

    assert stats.texts_skipped == 2
    assert stats.texts_done == 3
    assert len(client.tts_calls) == 3
    assert (workspace["texts"] / "текст1.mp3").read_bytes() == already
    assert (workspace["texts"] / "текст2.mp3").read_bytes() == already
    assert (workspace["texts"] / "текст3.mp3").exists()


def test_uses_voices_from_account(workspace, store, monkeypatch):
    """Обходной путь для бесплатного тарифа: голоса созданы на сайте заранее."""
    write_texts(workspace["texts"], 4)
    client = FakeClient()
    client.account_catalog = [
        ("voice-a", "Диктор", "generated"),
        ("voice-b", "Ведущая", "generated"),
        ("voice-c", "Рассказчик", "generated"),
    ]

    settings = make_settings(workspace, voice_source=SOURCE_ACCOUNT)
    stats = run_with(monkeypatch, settings, store, client)

    # Ни одного обращения к Voice Design: на бесплатном тарифе оно запрещено.
    assert client.designs == []
    assert client.creates == []
    assert stats.voices_reused == 3
    assert stats.texts_done == 4

    # Порядок — по имени голоса, тот же, что человек видит в списке:
    # Ведущая, Диктор, Рассказчик.
    used = [call[0] for call in client.tts_calls]
    assert used == ["voice-b", "voice-a", "voice-c", "voice-b"]


def test_account_mode_needs_no_prompts_folder(workspace, store, monkeypatch):
    write_texts(workspace["texts"], 1)
    client = FakeClient()
    client.account_catalog = [("voice-a", "Диктор", "generated")]

    settings = make_settings(
        workspace, voice_source=SOURCE_ACCOUNT, prompts_dir=str(workspace["root"] / "нет-такой")
    )
    stats = run_with(monkeypatch, settings, store, client)

    assert stats.texts_done == 1


def test_account_mode_respects_selection(workspace, store, monkeypatch):
    write_texts(workspace["texts"], 2)
    client = FakeClient()
    client.account_catalog = [
        ("voice-a", "Диктор", "generated"),
        ("voice-b", "Ведущая", "generated"),
        ("voice-c", "Рассказчик", "generated"),
    ]

    settings = make_settings(
        workspace, voice_source=SOURCE_ACCOUNT, selected_voice_ids=["voice-c", "voice-a"]
    )
    run_with(monkeypatch, settings, store, client)

    assert [call[0] for call in client.tts_calls] == ["voice-c", "voice-a"]


def test_account_mode_skips_library_voices_by_default(workspace, store, monkeypatch):
    """Без явного выбора берём свои голоса, а не всю общую библиотеку."""
    write_texts(workspace["texts"], 1)
    client = FakeClient()
    client.account_catalog = [
        ("premade-1", "Rachel", "premade"),
        ("voice-a", "Мой голос", "generated"),
    ]

    settings = make_settings(workspace, voice_source=SOURCE_ACCOUNT)
    run_with(monkeypatch, settings, store, client)

    assert client.tts_calls[0][0] == "voice-a"


def test_account_mode_without_voices_is_explained(workspace, store, monkeypatch):
    write_texts(workspace["texts"], 1)
    client = FakeClient()
    client.account_catalog = []

    settings = make_settings(workspace, voice_source=SOURCE_ACCOUNT)
    with pytest.raises(PreflightError, match="Voice Design"):
        run_with(monkeypatch, settings, store, client)


def test_account_mode_survives_missing_selected_voice(workspace, store, monkeypatch):
    write_texts(workspace["texts"], 1)
    client = FakeClient()
    client.account_catalog = [("voice-a", "Диктор", "generated")]

    settings = make_settings(
        workspace, voice_source=SOURCE_ACCOUNT, selected_voice_ids=["voice-a", "удалённый"]
    )
    stats = run_with(monkeypatch, settings, store, client)

    assert stats.texts_done == 1
    assert client.tts_calls[0][0] == "voice-a"


def test_account_mode_costs_nothing_to_prepare(workspace):
    write_texts(workspace["texts"], 2)
    plan = estimate_plan(make_settings(workspace, voice_source=SOURCE_ACCOUNT))

    # Голоса уже созданы, значит кредитов на их подготовку не нужно.
    assert plan["design_credits"] == 0


def test_run_starts_with_seller_format_proxy(workspace, store, monkeypatch):
    """Адрес вида адрес:порт:логин:пароль ронял запуск ещё до первого запроса."""
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 1)

    settings = make_settings(workspace, max_voices=1, proxy_url="1.2.3.4:8000:wVgThP:kjSdfL")
    stats = run_with(monkeypatch, settings, store, FakeClient())

    assert stats.stopped_reason == ""
    assert stats.texts_done == 1


def test_run_starts_with_unparseable_proxy(workspace, store, monkeypatch):
    """Совсем непонятный адрес отбрасывается, но работу не срывает."""
    write_prompts(workspace["prompts"], 1)
    write_texts(workspace["texts"], 1)

    settings = make_settings(workspace, max_voices=1, proxy_url="[::1:8080")
    assert settings.proxy_url == ""

    stats = run_with(monkeypatch, settings, store, FakeClient())
    assert stats.texts_done == 1


def test_estimate_on_empty_folders(workspace):
    plan = estimate_plan(make_settings(workspace))
    assert plan["texts"] == 0
    assert plan["characters"] == 0
