"""Настройки должны сохраняться сами, а не только при запуске и выходе."""

from __future__ import annotations

import pytest

pytest.importorskip("tkinter")

import tkinter as tk

from elevenlabs_voiceover.config import Settings
from elevenlabs_voiceover.logging_setup import setup_logging


@pytest.fixture
def app(isolated_data_dir):
    from elevenlabs_voiceover.gui import App

    setup_logging()
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"нет графического окружения: {exc}")
    root.withdraw()

    instance = App(root)
    try:
        yield instance
    finally:
        instance.state.close()
        root.destroy()


def flush(app) -> None:
    """Дождаться отложенной записи настроек."""
    app._save_now()
    app.root.update_idletasks()


def reload_settings() -> Settings:
    return Settings.load()


# ----------------------------------------------------------------------
def test_autosave_is_armed(app):
    assert app._autosave_ready is True


def test_change_is_scheduled_for_saving(app):
    app.var_max_voices.set(7)
    app.root.update_idletasks()
    assert app._save_job is not None


def test_folder_is_saved(app, tmp_path):
    app.var_texts_dir.set(str(tmp_path))
    flush(app)
    assert reload_settings().texts_dir == str(tmp_path)


def test_proxy_is_saved(app):
    app.var_proxy.set("socks5h://127.0.0.1:1080")
    flush(app)
    assert reload_settings().proxy_url == "socks5h://127.0.0.1:1080"


def test_seller_format_proxy_is_saved_normalised(app):
    app.var_proxy.set("1.2.3.4:8000:wVgThP:kjSdfL")
    flush(app)
    assert reload_settings().proxy_url == "http://wVgThP:kjSdfL@1.2.3.4:8000"


def test_checkbox_is_saved(app):
    app.var_ignore_system_proxy.set(True)
    flush(app)
    assert reload_settings().ignore_system_proxy is True


def test_slider_is_saved(app):
    app.var_stability.set(0.23)
    flush(app)
    assert abs(reload_settings().stability - 0.23) < 1e-6


def test_guidance_is_saved(app):
    app.var_guidance.set(30.0)
    flush(app)
    assert reload_settings().guidance_scale == 30.0


def test_model_is_saved(app):
    app.var_model.set("eleven_multilingual_v2")
    flush(app)
    assert reload_settings().model_id == "eleven_multilingual_v2"


def test_preview_text_is_saved(app):
    text = "Новый текст прослушивания, достаточно длинный для того, чтобы пройти проверку минимальной длины в сто символов."
    app.txt_preview.delete("1.0", "end")
    app.txt_preview.insert("1.0", text)
    flush(app)
    assert reload_settings().preview_text == text


def test_api_key_is_saved_when_remembered(app):
    app.var_remember_key.set(True)
    app.var_api_key.set("sk_saved_key_1234567890")
    flush(app)
    assert reload_settings().api_key == "sk_saved_key_1234567890"


def test_api_key_is_not_saved_when_not_remembered(app):
    app.var_remember_key.set(False)
    app.var_api_key.set("sk_secret_not_to_store_1234")
    flush(app)
    assert reload_settings().api_key == ""


def test_every_variable_is_watched(app):
    """Ни одно поле окна не должно остаться без автосохранения."""
    unwatched = [
        name
        for name, value in vars(app).items()
        if name.startswith("var_") and isinstance(value, tk.Variable)
        and not value.trace_info()
    ]
    assert unwatched == []


def test_voice_mode_hint_shows_file_count(app, tmp_path):
    """Режим раздачи голосов должен объяснять себя числами, а не названием."""
    from elevenlabs_voiceover.config import MODE_ALL_VOICES, MODE_ROUND_ROBIN, VOICE_MODES

    texts = tmp_path / "тексты"
    texts.mkdir()
    for i in range(4):
        (texts / f"{i}.txt").write_text("Короткий текст для проверки.", encoding="utf-8")

    prompts = tmp_path / "промпты"
    prompts.mkdir()
    for i in range(3):
        (prompts / f"{i}.txt").write_text("Native Russian. Спокойный голос.", encoding="utf-8")

    app.var_prompts_dir.set(str(prompts))
    app.var_texts_dir.set(str(texts))
    app.var_max_voices.set(3)

    app.var_voice_mode.set(VOICE_MODES[MODE_ROUND_ROBIN])
    app._refresh_estimate()
    assert "4 файлов" in app.lbl_voice_mode.cget("text")

    app.var_voice_mode.set(VOICE_MODES[MODE_ALL_VOICES])
    app._refresh_estimate()
    hint = app.lbl_voice_mode.cget("text")
    assert "12 файлов" in hint
    # Умножение файлов и расхода — то, о чём надо предупредить заметно.
    assert app.lbl_voice_mode.cget("style") == "Bad.TLabel"


def test_done_action_is_saved(app):
    from elevenlabs_voiceover.config import DONE_ACTIONS, DONE_DELETE

    app.var_done_action.set(DONE_ACTIONS[DONE_DELETE])
    flush(app)
    assert reload_settings().done_action == DONE_DELETE


def test_deletion_is_marked_as_dangerous(app):
    from elevenlabs_voiceover.config import DONE_ACTIONS, DONE_DELETE, DONE_KEEP

    app.var_done_action.set(DONE_ACTIONS[DONE_DELETE])
    app._refresh_done_hint()
    assert app.lbl_done_action.cget("style") == "Bad.TLabel"
    assert "неоткуда" in app.lbl_done_action.cget("text")

    app.var_done_action.set(DONE_ACTIONS[DONE_KEEP])
    app._refresh_done_hint()
    assert app.lbl_done_action.cget("style") == "Hint.TLabel"


def test_keeping_texts_is_the_default(app):
    from elevenlabs_voiceover.config import DONE_KEEP

    assert reload_settings().done_action == DONE_KEEP


def test_save_beside_flag_is_saved(app):
    app.var_save_beside.set(True)
    flush(app)
    assert reload_settings().save_next_to_texts is True


def test_save_beside_hides_output_folder(app):
    caption = app.folder_rows["output"][0]

    app.var_save_beside.set(True)
    app._on_save_beside_changed()
    app.root.update_idletasks()
    assert not caption.winfo_ismapped()

    app.var_save_beside.set(False)
    app._on_save_beside_changed()
    app.root.update_idletasks()
    assert caption.winfo_manager()


def test_save_beside_explains_result(app):
    app.var_save_beside.set(True)
    app._on_save_beside_changed()

    hint = app.lbl_beside.cget("text")
    assert "текст1.mp3" in hint.replace("текст1" + ".mp3", "текст1.mp3")


def test_voice_source_is_saved(app):
    from elevenlabs_voiceover.config import SOURCE_ACCOUNT, VOICE_SOURCES

    app.var_voice_source.set(VOICE_SOURCES[SOURCE_ACCOUNT])
    flush(app)
    assert reload_settings().voice_source == SOURCE_ACCOUNT


def test_voice_list_is_hidden_at_start(app):
    """По умолчанию источник — промпты, список голосов аккаунта не нужен."""
    app.root.update_idletasks()
    assert not app.frame_account_voices.winfo_ismapped()


def test_account_mode_hides_prompts_folder(app):
    from elevenlabs_voiceover.config import SOURCE_ACCOUNT, SOURCE_DESIGN, VOICE_SOURCES

    caption = app.folder_rows["prompts"][0]

    app.var_voice_source.set(VOICE_SOURCES[SOURCE_ACCOUNT])
    app._on_voice_source_changed()
    app.root.update_idletasks()
    assert not caption.winfo_ismapped()

    app.var_voice_source.set(VOICE_SOURCES[SOURCE_DESIGN])
    app._on_voice_source_changed()
    app.root.update_idletasks()
    assert caption.winfo_manager()


def test_selected_voices_are_saved(app):
    from elevenlabs_voiceover.api_client import AccountVoice

    app._on_voices_loaded([
        AccountVoice("v1", "Первый", "generated"),
        AccountVoice("v2", "Второй", "generated"),
    ])
    app.list_voices.selection_set(0)
    flush(app)

    assert reload_settings().selected_voice_ids == ["v1"]


def test_selection_survives_list_reload(app):
    """Обновление списка не должно сбрасывать отмеченные голоса."""
    from elevenlabs_voiceover.api_client import AccountVoice

    voices = [AccountVoice("v1", "Первый", "generated"), AccountVoice("v2", "Второй", "generated")]
    app._on_voices_loaded(voices)
    app.list_voices.selection_set(1)
    flush(app)

    app._on_voices_loaded(voices)
    assert app._selected_voice_ids() == ["v2"]


def test_select_own_skips_library_voices(app):
    from elevenlabs_voiceover.api_client import AccountVoice

    app._on_voices_loaded([
        AccountVoice("v1", "Мой", "generated"),
        AccountVoice("p1", "Rachel", "premade"),
    ])
    app._select_own_voices()

    assert app._selected_voice_ids() == ["v1"]


def test_settings_survive_restart(app, tmp_path):
    app.var_output_dir.set(str(tmp_path))
    app.var_chunk.set(1200)
    app.var_reserve.set(2500)
    flush(app)

    restored = reload_settings()
    assert restored.output_dir == str(tmp_path)
    assert restored.chunk_target_chars == 1200
    assert restored.reserve_credits == 2500
