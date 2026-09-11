"""Сторож нагрузки и настройки.

Сторож придерживает бота, когда компьютеру тяжело от другой работы — рядом
собирается партия роликов или идёт экспорт. Порог берётся по выдержке, а не по
мгновенному значению: процессор скачет до ста процентов от любого чиха, и бот,
засыпающий на каждом скачке, был бы бесполезен.
"""
from __future__ import annotations

from pathlib import Path

from videobot import config as config_module
from videobot.guard import Guard


def test_short_spike_does_not_stop_the_bot():
    guard = Guard(limit_percent=85, grace_s=30)

    assert guard.feed(99.0, moment=0.0) is True
    assert guard.feed(99.0, moment=10.0) is True
    assert guard.paused is False


def test_sustained_load_puts_the_bot_on_pause():
    guard = Guard(limit_percent=85, grace_s=30)
    guard.feed(99.0, moment=0.0)

    assert guard.feed(99.0, moment=31.0) is False
    assert guard.paused is True


def test_bot_resumes_by_itself_when_the_load_drops():
    guard = Guard(limit_percent=85, grace_s=30)
    guard.feed(99.0, moment=0.0)
    guard.feed(99.0, moment=31.0)

    assert guard.feed(20.0, moment=40.0) is True
    assert guard.paused is False


def test_load_falling_between_spikes_resets_the_countdown():
    """Иначе редкие всплески за час накопились бы в ложную паузу."""
    guard = Guard(limit_percent=85, grace_s=30)
    guard.feed(99.0, moment=0.0)
    guard.feed(10.0, moment=5.0)
    guard.feed(99.0, moment=10.0)

    assert guard.feed(99.0, moment=35.0) is True


def test_settings_survive_a_save_and_load(tmp_path: Path):
    settings = config_module.Settings(token="123:abc", admin_id=42,
                                      registry_path="D:/данные роликов.jsonl")
    config_module.save(tmp_path, settings)
    back = config_module.load(tmp_path)

    assert back.token == "123:abc"
    assert back.admin_id == 42
    assert back.registry_path == "D:/данные роликов.jsonl"


def test_broken_settings_do_not_stop_the_window(tmp_path: Path):
    """Иначе испорченный файл оставил бы человека без окна, где его исправить."""
    config_module.path_for(tmp_path).write_text("{ это не json", encoding="utf-8")

    assert config_module.load(tmp_path).token == ""


def test_unknown_field_in_an_old_file_is_ignored(tmp_path: Path):
    config_module.path_for(tmp_path).write_text(
        '{"token": "1:a", "давно_убранная_настройка": 5}', encoding="utf-8")

    assert config_module.load(tmp_path).token == "1:a"


def test_missing_token_is_named_as_the_reason(tmp_path: Path):
    troubles = config_module.problems(config_module.Settings(registry_path=__file__))

    assert any("токен" in item for item in troubles)


def test_token_without_a_colon_is_caught_before_the_bot_starts(tmp_path: Path):
    """Так ошибка видна сразу, а не превращается в отказ Telegram при запуске."""
    troubles = config_module.problems(
        config_module.Settings(token="просто строка", registry_path=__file__))

    assert any("двоеточие" in item for item in troubles)


def test_absent_registry_file_is_named_by_path(tmp_path: Path):
    troubles = config_module.problems(
        config_module.Settings(token="1:a", registry_path=str(tmp_path / "нет.jsonl")))

    assert any("не найден" in item for item in troubles)


def test_everything_filled_leaves_no_complaints():
    settings = config_module.Settings(token="123:abc", registry_path=__file__)

    assert config_module.problems(settings) == []
