import json

from elevenlabs_voiceover.config import (
    DEFAULT_GUIDANCE,
    DEFAULT_PREVIEW_TEXT,
    GUIDANCE_MAX,
    GUIDANCE_MIN,
    MODE_ALL_VOICES,
    MODE_ROUND_ROBIN,
    VOICE_PREVIEW_MAX_CHARS,
    VOICE_PREVIEW_MIN_CHARS,
    Settings,
)


def test_defaults_are_valid():
    s = Settings()
    assert s.voice_mode == MODE_ROUND_ROBIN
    assert s.max_voices == 3
    assert VOICE_PREVIEW_MIN_CHARS <= len(s.preview_text) <= VOICE_PREVIEW_MAX_CHARS


def test_out_of_range_values_are_clamped():
    s = Settings(max_voices=999, stability=5.0, speed=99.0, chunk_target_chars=10, max_retries=-3)
    assert s.max_voices == 50
    assert s.stability == 1.0
    assert s.speed == 4.0
    assert s.chunk_target_chars == 200
    assert s.max_retries == 0


def test_garbage_values_fall_back_to_defaults():
    s = Settings(stability="не число", chunk_target_chars="abc")  # type: ignore[arg-type]
    assert s.stability == 0.5
    assert s.chunk_target_chars == 2500


def test_unknown_voice_mode_falls_back():
    assert Settings(voice_mode="что-то своё").voice_mode == MODE_ROUND_ROBIN


def test_known_voice_mode_survives():
    assert Settings(voice_mode=MODE_ALL_VOICES).voice_mode == MODE_ALL_VOICES


def test_short_preview_is_extended():
    s = Settings(preview_text="Слишком коротко")
    assert len(s.preview_text) >= VOICE_PREVIEW_MIN_CHARS


def test_empty_preview_uses_default():
    assert Settings(preview_text="   ").preview_text == DEFAULT_PREVIEW_TEXT


def test_long_preview_is_trimmed():
    s = Settings(preview_text="а" * 5000)
    assert len(s.preview_text) <= VOICE_PREVIEW_MAX_CHARS


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "config.json"
    original = Settings(
        api_key="sk_test_1234567890",
        prompts_dir="/tmp/prompts",
        texts_dir="/tmp/texts",
        output_dir="/tmp/out",
        max_voices=5,
        voice_mode=MODE_ALL_VOICES,
        stability=0.31,
    )
    original.save(path)

    loaded = Settings.load(path)
    assert loaded.api_key == "sk_test_1234567890"
    assert loaded.prompts_dir == "/tmp/prompts"
    assert loaded.max_voices == 5
    assert loaded.voice_mode == MODE_ALL_VOICES
    assert abs(loaded.stability - 0.31) < 1e-9


def test_key_is_not_written_when_not_remembered(tmp_path):
    path = tmp_path / "config.json"
    Settings(api_key="sk_secret_value_here", remember_api_key=False).save(path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["api_key"] == ""
    assert "sk_secret_value_here" not in path.read_text(encoding="utf-8")


def test_to_dict_can_exclude_secrets():
    s = Settings(api_key="sk_secret_value_here")
    assert s.to_dict(include_secrets=False)["api_key"] == ""
    assert s.to_dict(include_secrets=True)["api_key"] == "sk_secret_value_here"


def test_unknown_fields_in_config_are_ignored(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"max_voices": 4, "поле_из_будущего": 1}), encoding="utf-8")

    loaded = Settings.load(path)
    assert loaded.max_voices == 4


def test_broken_config_does_not_crash(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{это не json", encoding="utf-8")
    assert Settings.load(path).max_voices == 3


def test_missing_config_returns_defaults(tmp_path):
    assert Settings.load(tmp_path / "нет-такого.json").max_voices == 3


def test_api_key_from_environment(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_from_env_123456")
    assert Settings(api_key="").resolved_api_key() == "sk_from_env_123456"


def test_explicit_key_wins_over_environment(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_from_env_123456")
    assert Settings(api_key="sk_explicit_123456").resolved_api_key() == "sk_explicit_123456"


def test_guidance_default_matches_elevenlabs():
    # В API у guidance_scale значение по умолчанию 5 на шкале 0–100.
    assert DEFAULT_GUIDANCE == 5.0
    assert (GUIDANCE_MIN, GUIDANCE_MAX) == (0.0, 100.0)
    assert Settings().guidance_scale == 5.0


def test_guidance_accepts_documented_example_values():
    # В примерах документации ElevenLabs используются 25–40.
    for value in (25.0, 30.0, 35.0, 40.0):
        assert Settings(guidance_scale=value).guidance_scale == value


def test_guidance_is_clamped_to_scale():
    assert Settings(guidance_scale=500).guidance_scale == GUIDANCE_MAX
    assert Settings(guidance_scale=-10).guidance_scale == GUIDANCE_MIN


def test_voice_settings_payload_shape():
    payload = Settings().voice_settings_payload()
    assert set(payload) == {"stability", "similarity_boost", "style", "use_speaker_boost", "speed"}
