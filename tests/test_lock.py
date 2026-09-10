"""Замок на вторую копию программы.

Две копии дерутся за один токен: Telegram отдаёт обновления только одному
опросу, второму отвечает отказом. Со стороны это бот, который отвечает через
раз, и по такому симптому причина не угадывается — поэтому вторую копию проще
не пускать.
"""
from __future__ import annotations

import os
from pathlib import Path

from videobot import lock


def test_first_copy_takes_the_lock(tmp_path: Path):
    assert lock.take(tmp_path) == 0
    assert lock.path_for(tmp_path).read_text(encoding="utf-8") == str(os.getpid())


def test_second_copy_is_told_who_holds_the_lock(tmp_path: Path):
    """Номер процесса — не для красоты: по нему копию находят и закрывают."""
    lock.path_for(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    lock.path_for(tmp_path).write_text(str(os.getppid()), encoding="utf-8")

    assert lock.take(tmp_path) == os.getppid()


def test_lock_left_by_a_dead_copy_does_not_block_forever(tmp_path: Path):
    """После выключения питания файл остаётся, и без проверки программа
    больше никогда бы не запустилась."""
    lock.path_for(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    lock.path_for(tmp_path).write_text("999999", encoding="utf-8")

    assert lock.take(tmp_path) == 0


def test_our_own_lock_does_not_block_us(tmp_path: Path):
    lock.take(tmp_path)
    assert lock.take(tmp_path) == 0


def test_garbage_in_the_lock_file_is_ignored(tmp_path: Path):
    lock.path_for(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    lock.path_for(tmp_path).write_text("не число", encoding="utf-8")

    assert lock.take(tmp_path) == 0


def test_releasing_removes_the_lock(tmp_path: Path):
    lock.take(tmp_path)
    lock.release(tmp_path)

    assert not lock.path_for(tmp_path).exists()


def test_we_do_not_remove_someone_elses_lock(tmp_path: Path):
    """Чужой замок трогать нельзя: та копия работает и после нашего выхода."""
    lock.path_for(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    lock.path_for(tmp_path).write_text(str(os.getppid()), encoding="utf-8")

    lock.release(tmp_path)
    assert lock.path_for(tmp_path).exists()


def test_second_copy_gets_a_clear_answer_and_not_a_crash(tmp_path: Path, monkeypatch):
    """Человек должен прочитать «уже запущена», а не гадать над пустым окном."""
    from videobot import cli

    monkeypatch.setattr(cli, "_folder", lambda: tmp_path)
    (tmp_path / "данные").mkdir(parents=True, exist_ok=True)
    lock.path_for(tmp_path / "данные").write_text(str(os.getppid()), encoding="utf-8")

    said: list[str] = []
    monkeypatch.setattr(cli, "_say", said.append)

    assert cli.main(["gui"]) == 3
    assert any("уже запущена" in line for line in said)
