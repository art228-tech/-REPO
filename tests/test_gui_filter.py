"""Кнопка «Отобрать готовые файлы в папке…» в окне программы."""

from __future__ import annotations

import queue

import pytest

pytest.importorskip("tkinter")

import tkinter as tk
from tkinter import filedialog, messagebox

from elevenlabs_voiceover.logging_setup import setup_logging

FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 413
FRAME_SECONDS = 1152 / 44100


def write_mp3(folder, name: str, seconds: float):
    path = folder / name
    path.write_bytes(FRAME * max(1, round(seconds / FRAME_SECONDS)))
    return path


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


@pytest.fixture
def ready(tmp_path):
    """Папка, в которой уже лежат готовые озвучки разной длины."""
    folder = tmp_path / "готово"
    folder.mkdir()
    write_mp3(folder, "короткая.mp3", 4)
    write_mp3(folder, "нормальная.mp3", 12)
    write_mp3(folder, "длинная.mp3", 25)
    return folder


class Dialogs:
    """Подменённые окна вопросов и сообщений."""

    def __init__(self, monkeypatch, *, folder=None, answer=True):
        self.answer = answer
        self.asked: list = []
        self.shown: list = []

        monkeypatch.setattr(filedialog, "askdirectory", lambda **kw: str(folder) if folder else "")
        monkeypatch.setattr(messagebox, "askyesno", self._askyesno)
        monkeypatch.setattr(messagebox, "showinfo", self._show)
        monkeypatch.setattr(messagebox, "showwarning", self._show)

    def _askyesno(self, _title, message, **kwargs):
        self.asked.append(message)
        return self.answer

    def _show(self, _title, message, **kwargs):
        self.shown.append(message)

    @property
    def texts(self) -> str:
        return "\n".join(self.asked + self.shown)


def pump(app) -> None:
    """Дождаться рабочих потоков и разобрать очередь событий окна.

    Удаление начинается вторым потоком уже после ответа на вопрос, поэтому
    ждать и разбирать очередь приходится по кругу.
    """
    for _ in range(10):
        if app.worker:
            app.worker.join(timeout=20)
        drained = False
        try:
            while True:
                app._handle_event(app.events.get_nowait())
                drained = True
        except queue.Empty:
            pass
        if not drained and not (app.worker and app.worker.is_alive()):
            return


def names(folder):
    return sorted(p.name for p in folder.iterdir())


def set_limits(app, minimum, maximum) -> None:
    app.var_min_duration.set(minimum)
    app.var_max_duration.set(maximum)


# ======================================================================
def test_deletes_what_does_not_fit(app, ready, monkeypatch):
    dialogs = Dialogs(monkeypatch, folder=ready, answer=True)
    set_limits(app, 10, 16)

    app._filter_ready_files()
    pump(app)

    assert names(ready) == ["нормальная.mp3"]
    assert "Удалено файлов: 2" in dialogs.texts


def test_asks_before_deleting_and_obeys_no(app, ready, monkeypatch):
    dialogs = Dialogs(monkeypatch, folder=ready, answer=False)
    set_limits(app, 10, 16)

    app._filter_ready_files()
    pump(app)

    assert names(ready) == ["длинная.mp3", "короткая.mp3", "нормальная.mp3"]
    assert dialogs.asked, "перед удалением обязателен вопрос"
    assert "Ничего не удалено" in app.lbl_status.cget("text")


def test_question_names_the_files_and_counts(app, ready, monkeypatch):
    """Согласие дают, увидев конкретные имена, а не только счётчик."""
    dialogs = Dialogs(monkeypatch, folder=ready, answer=False)
    set_limits(app, 10, 16)

    app._filter_ready_files()
    pump(app)

    question = dialogs.asked[0]
    assert "короткая.mp3" in question
    assert "длинная.mp3" in question
    assert "нормальная.mp3" not in question
    assert "короче — 1, длиннее — 1" in question


def test_folder_is_not_touched_without_limits(app, ready, monkeypatch):
    dialogs = Dialogs(monkeypatch, folder=ready, answer=True)
    set_limits(app, 0, 0)

    app._filter_ready_files()
    pump(app)

    assert len(names(ready)) == 3
    assert "Границы длительности не заданы" in dialogs.texts


def test_cancelled_folder_choice_does_nothing(app, ready, monkeypatch):
    Dialogs(monkeypatch, folder=None, answer=True)
    set_limits(app, 10, 16)

    app._filter_ready_files()
    pump(app)

    assert len(names(ready)) == 3


def test_nothing_to_delete_is_reported(app, tmp_path, monkeypatch):
    folder = tmp_path / "ровные"
    folder.mkdir()
    write_mp3(folder, "первая.mp3", 12)
    write_mp3(folder, "вторая.mp3", 14)

    dialogs = Dialogs(monkeypatch, folder=folder, answer=True)
    set_limits(app, 10, 16)

    app._filter_ready_files()
    pump(app)

    assert len(names(folder)) == 2
    assert not dialogs.asked
    assert "Удалять нечего" in dialogs.texts


def test_empty_folder_is_explained(app, tmp_path, monkeypatch):
    folder = tmp_path / "пусто"
    folder.mkdir()

    dialogs = Dialogs(monkeypatch, folder=folder, answer=True)
    set_limits(app, 10, 16)

    app._filter_ready_files()
    pump(app)

    assert "нет ни одного mp3" in dialogs.texts


def test_service_folders_are_spared(app, ready, monkeypatch):
    for service in ("_voices", "_chunks"):
        (ready / service).mkdir()
        write_mp3(ready / service, "внутри.mp3", 2)

    Dialogs(monkeypatch, folder=ready, answer=True)
    set_limits(app, 10, 16)

    app._filter_ready_files()
    pump(app)

    assert (ready / "_voices" / "внутри.mp3").exists()
    assert (ready / "_chunks" / "внутри.mp3").exists()


def test_only_lower_limit_from_the_window(app, ready, monkeypatch):
    Dialogs(monkeypatch, folder=ready, answer=True)
    set_limits(app, 10, 0)

    app._filter_ready_files()
    pump(app)

    assert names(ready) == ["длинная.mp3", "нормальная.mp3"]


def test_only_upper_limit_from_the_window(app, ready, monkeypatch):
    Dialogs(monkeypatch, folder=ready, answer=True)
    set_limits(app, 0, 16)

    app._filter_ready_files()
    pump(app)

    assert names(ready) == ["короткая.mp3", "нормальная.mp3"]


def test_buttons_are_free_again_afterwards(app, ready, monkeypatch):
    """Кнопка «Начать озвучку» не должна остаться заблокированной."""
    Dialogs(monkeypatch, folder=ready, answer=True)
    set_limits(app, 10, 16)

    app._filter_ready_files()
    pump(app)

    assert str(app.btn_start.cget("state")) == "normal"
