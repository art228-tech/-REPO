"""Поиск реестра автомонтажа рядом с программой.

Путь к нему — единственная настройка, которую можно вычислить: автомонтаж
кладёт реестр в `capcut_uniq_data` внутри своей папки, а обе программы обычно
лежат по соседству. Спрашивать такое у человека незачем.
"""
from __future__ import annotations

from pathlib import Path

from videobot import registry


def _make(where: Path) -> Path:
    """Кладёт реестр там, где его создал бы автомонтаж."""
    target = where / registry.DATA_DIR / registry.FILE_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"name": "ролик"}\n', encoding="utf-8")
    return target


def test_registry_next_door_is_found(tmp_path: Path, monkeypatch):
    """Обычный случай: обе программы распакованы рядом."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "дом"))
    program = tmp_path / "бот"
    program.mkdir()
    wanted = _make(tmp_path / "автомонтаж")

    assert registry.find_nearby(program) == wanted


def test_registry_inside_our_own_folder_is_found(tmp_path: Path, monkeypatch):
    """Кто-то распакует бота прямо в папку автомонтажа — это тоже сработает."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "дом"))
    program = tmp_path / "бот"
    program.mkdir()
    wanted = _make(program)

    assert registry.find_nearby(program) == wanted


def test_registry_on_the_desktop_is_found(tmp_path: Path, monkeypatch):
    home = tmp_path / "дом"
    (home / "Desktop").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    program = tmp_path / "где-то" / "бот"
    program.mkdir(parents=True)
    wanted = _make(home / "Desktop" / "автомонтаж")

    assert registry.find_nearby(program) == wanted


def test_the_freshest_registry_wins(tmp_path: Path, monkeypatch):
    """У человека может лежать старая копия автомонтажа — она не нужна."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "дом"))
    program = tmp_path / "бот"
    program.mkdir()

    old = _make(tmp_path / "автомонтаж старый")
    new = _make(tmp_path / "автомонтаж новый")
    import os
    os.utime(old, (1_000_000, 1_000_000))

    assert registry.find_nearby(program) == new


def test_nothing_found_is_not_an_error(tmp_path: Path, monkeypatch):
    """Реестра ещё нет, пока автомонтаж не собрал ни одного ролика."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "дом"))
    program = tmp_path / "бот"
    program.mkdir()

    assert registry.find_nearby(program) is None


def test_search_does_not_wander_deep(tmp_path: Path, monkeypatch):
    """Обшаривать диск целиком долго, а чужой файл издалека хуже ненайденного."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "дом"))
    program = tmp_path / "бот"
    program.mkdir()
    _make(tmp_path / "а" / "б" / "в" / "автомонтаж")

    assert registry.find_nearby(program) is None
