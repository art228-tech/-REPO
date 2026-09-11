"""Поиск данных ролика по имени экспортированного файла.

Экспортированный из CapCut файл несёт только имя, всё остальное лежит в реестре
автомонтажа. Ошибиться тут дороже, чем не найти: подставленные чужие данные
никак себя не проявят, пока через неделю не окажется, что статистика меряла не
то. Поэтому при любой неоднозначности ролик отклоняется.
"""
from __future__ import annotations

import json
from pathlib import Path

from videobot import registry


def _registry(tmp_path: Path, *names: str) -> dict:
    target = tmp_path / "данные роликов.jsonl"
    target.write_text(
        "\n".join(json.dumps({"name": name, "background": "blur"}, ensure_ascii=False)
                  for name in names),
        encoding="utf-8")
    return registry.read(target)


def test_exact_name_is_found(tmp_path: Path):
    known = _registry(tmp_path, "auto_0906_1420_007")
    found = registry.match(Path("D:/экспорт/auto_0906_1420_007.mp4"), known)

    assert found.ok
    assert found.name == "auto_0906_1420_007"


def test_copy_suffix_from_second_export_is_ignored(tmp_path: Path):
    """CapCut дописывает «(1)», когда такой файл уже лежит в папке."""
    known = _registry(tmp_path, "auto_0906_1420_007")

    assert registry.match(Path("auto_0906_1420_007 (1).mp4"), known).ok
    assert registry.match(Path("auto_0906_1420_007(2).mp4"), known).ok


def test_renamed_file_is_found_by_the_name_inside(tmp_path: Path):
    """Файл могли переименовать, дописав своё — имя проекта осталось внутри."""
    known = _registry(tmp_path, "auto_0906_1420_007")
    found = registry.match(Path("auto_0906_1420_007 финал.mp4"), known)

    assert found.ok
    assert found.name == "auto_0906_1420_007"


def test_unknown_name_is_refused(tmp_path: Path):
    known = _registry(tmp_path, "auto_0906_1420_007")
    found = registry.match(Path("случайное видео.mp4"), known)

    assert not found.ok
    assert "нет данных" in found.problem


def test_ambiguous_name_is_refused_rather_than_guessed(tmp_path: Path):
    """Два имени равной длины внутри — угадывать нельзя, данные разойдутся."""
    known = _registry(tmp_path, "ролик_аа", "ролик_бб")
    found = registry.match(Path("ролик_аа и ролик_бб.mp4"), known)

    assert not found.ok
    assert "несколько" in found.problem


def test_longer_name_wins_over_its_own_beginning(tmp_path: Path):
    """«auto_007» — начало «auto_007_дубль», и это не повод отклонять ролик."""
    known = _registry(tmp_path, "auto_007", "auto_007_дубль")
    found = registry.match(Path("auto_007_дубль.mp4"), known)

    assert found.ok
    assert found.name == "auto_007_дубль"


def test_same_video_twice_in_one_batch_is_caught(tmp_path: Path):
    """Иначе одна и та же сборка ушла бы человеку дважды как разные ролики."""
    known = _registry(tmp_path, "ролик")
    found = registry.match_all([Path("ролик.mp4"), Path("ролик (1).mp4")], known)

    assert found[0].ok
    assert not found[1].ok
    assert "уже есть в списке" in found[1].problem


def test_broken_line_does_not_take_the_registry_with_it(tmp_path: Path):
    """Запись могла оборваться на выключении — остальные ролики не виноваты."""
    target = tmp_path / "данные роликов.jsonl"
    target.write_text('{"name": "целый"}\n{"name": "обор\n{"name": "второй"}\n',
                      encoding="utf-8")

    assert sorted(registry.read(target)) == ["второй", "целый"]


def test_missing_registry_reads_as_empty(tmp_path: Path):
    assert registry.read(tmp_path / "нет.jsonl") == {}
