"""Вставка из буфера обмена в поля окна.

Токен вводят только вставкой — руками его никто не набирает. А Ctrl+V в tkinter
привязан к латинской «v»: при русской раскладке приходит «Cyrillic_em», и
вставка молча не срабатывает. Человек видит пустое поле и не понимает, почему
программа его не принимает.

Нажатие с русской раскладкой здесь не подделать: синтезировать его можно только
если такая клавиша есть в раскладке системы, а на испытательной машине её нет.
Поэтому проверяется отдельно, что привязка заведена, и отдельно — что
обработчик делает ровно то, что нужно.

Тесты поднимают настоящее окно, поэтому нужен экран. Где его нет — пропускаются.
"""
from __future__ import annotations

import os

import pytest

tk = pytest.importorskip("tkinter")

needs_screen = pytest.mark.skipif(
    not os.environ.get("DISPLAY") and os.name != "nt",
    reason="нужен экран")


@pytest.fixture
def root():
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"окно не создать: {exc}")
    # Окно должно быть видимым: событий скрытому окну система не доставляет,
    # и проверка превратилась бы в проверку ничего.
    window.geometry("320x120")
    window.update()
    yield window
    window.destroy()


@pytest.fixture
def field(root):
    from videobot.gui import add_clipboard

    entry = tk.Entry(root)
    entry.pack()
    add_clipboard(entry)
    entry.focus_force()
    root.update()
    return entry


def _put(root, text: str) -> None:
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()


@needs_screen
def test_paste_works_with_the_latin_layout(root, field):
    _put(root, "8123456789:AAH-токен")
    field.event_generate("<Control-v>", when="now")
    root.update()

    assert field.get() == "8123456789:AAH-токен"


@needs_screen
def test_paste_does_not_double_the_text(root, field):
    """Без «break» Tk обработал бы нажатие ещё и сам, и копий стало бы две."""
    _put(root, "abc")
    field.event_generate("<Control-v>", when="now")
    root.update()

    assert field.get() == "abc"


@needs_screen
def test_russian_layout_shortcuts_are_bound(root, field):
    """Именно этих привязок и не хватало, чтобы токен вставлялся."""
    bound = set(field.bind())

    assert "<Control-Key-Cyrillic_em>" in bound   # Ctrl+V
    assert "<Control-Key-Cyrillic_es>" in bound   # Ctrl+C
    assert "<Control-Key-Cyrillic_che>" in bound  # Ctrl+X
    assert "<Control-Key-Cyrillic_ef>" in bound   # Ctrl+A


@needs_screen
def test_right_click_menu_is_bound(root, field):
    """Правая кнопка — запасной путь, когда сочетания перехватил кто-то ещё."""
    assert "<Button-3>" in set(field.bind())


@needs_screen
def test_handler_pastes_and_stops_further_handling(root, field):
    """Обработчик, который вешается на русские буквы, делает саму работу."""
    from videobot.gui import _clipboard_action

    _put(root, "вставленное")
    answer = _clipboard_action(field, "<<Paste>>")(None)
    root.update()

    assert field.get() == "вставленное"
    assert answer == "break"


@needs_screen
def test_copy_puts_the_selection_into_the_clipboard(root, field):
    """Строку ошибки из журнала часто проще скопировать, чем собирать отчёт."""
    from videobot.gui import _clipboard_action

    field.insert(0, "TelegramUnauthorizedError")
    field.select_range(0, "end")
    _put(root, "прежнее содержимое")

    _clipboard_action(field, "<<Copy>>")(None)
    root.update()

    assert root.clipboard_get() == "TelegramUnauthorizedError"


def test_every_shortcut_has_both_layouts():
    """Забыли пару — и сочетание снова работает только на одной раскладке."""
    from videobot.gui import CLIPBOARD_KEYS

    assert set(CLIPBOARD_KEYS) == {"<<Paste>>", "<<Copy>>", "<<Cut>>", "<<SelectAll>>"}
    for latin, cyrillic in CLIPBOARD_KEYS.values():
        assert len(latin) == 1
        assert cyrillic.startswith("Cyrillic_")
