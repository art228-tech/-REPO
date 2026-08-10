"""Проверка буфера обмена в настоящем окне Tk.

Разбор клавиш проверяется отдельно чистыми тестами; здесь важно другое — что
вставка действительно кладёт текст в поле, что кнопка «Вставить» работает и
что к полям привязано меню по правой кнопке.
"""

from __future__ import annotations

import pytest

pytest.importorskip("tkinter")

import tkinter as tk
from tkinter import ttk

from elevenlabs_voiceover import clipboard


@pytest.fixture
def root():
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"нет графического окружения: {exc}")
    window.withdraw()
    try:
        yield window
    finally:
        window.destroy()


def put_in_clipboard(widget, text: str) -> None:
    widget.clipboard_clear()
    widget.clipboard_append(text)
    widget.update_idletasks()


# ----------------------------------------------------------------------
def test_paste_puts_text_into_entry(root):
    entry = ttk.Entry(root)
    entry.pack()
    put_in_clipboard(root, "sk_test_key_1234567890")

    clipboard.paste(entry)

    assert entry.get() == "sk_test_key_1234567890"


def test_paste_strips_trailing_newline(root):
    entry = ttk.Entry(root)
    entry.pack()
    # Ключ, скопированный со страницы, часто приезжает с переводом строки.
    put_in_clipboard(root, "  sk_test_key_1234567890\r\n")

    clipboard.paste(entry)

    assert entry.get() == "sk_test_key_1234567890"


def test_paste_replaces_selected_text(root):
    entry = ttk.Entry(root)
    entry.pack()
    entry.insert(0, "старый_ключ")
    entry.select_range(0, "end")
    put_in_clipboard(root, "новый_ключ")

    clipboard.paste(entry)

    assert entry.get() == "новый_ключ"


def test_paste_inserts_at_cursor(root):
    entry = ttk.Entry(root)
    entry.pack()
    entry.insert(0, "ab")
    entry.icursor(1)
    put_in_clipboard(root, "X")

    clipboard.paste(entry)

    assert entry.get() == "aXb"


def test_paste_from_empty_clipboard_does_nothing(root):
    entry = ttk.Entry(root)
    entry.pack()
    entry.insert(0, "было")
    root.clipboard_clear()

    clipboard.paste(entry)

    assert entry.get() == "было"


def test_paste_into_text_widget(root):
    text = tk.Text(root)
    text.pack()
    put_in_clipboard(root, "первая строка\nвторая строка")

    clipboard.paste(text)

    # В многострочном поле переводы строк сохраняются.
    assert text.get("1.0", "end-1c") == "первая строка\nвторая строка"


# ----------------------------------------------------------------------
def test_copy_takes_selection(root):
    entry = ttk.Entry(root)
    entry.pack()
    entry.insert(0, "скопируй меня")
    entry.select_range(0, "end")
    root.clipboard_clear()

    clipboard.copy(entry)

    assert root.clipboard_get() == "скопируй меня"


def test_cut_removes_selection(root):
    entry = ttk.Entry(root)
    entry.pack()
    entry.insert(0, "вырежи это")
    entry.select_range(0, "end")

    clipboard.cut(entry)

    assert entry.get() == ""
    assert root.clipboard_get() == "вырежи это"


def test_select_all_in_entry(root):
    entry = ttk.Entry(root)
    entry.pack()
    entry.insert(0, "весь текст")

    clipboard.select_all(entry)

    assert entry.selection_get() == "весь текст"


def test_select_all_in_disabled_text(root):
    text = tk.Text(root)
    text.pack()
    text.insert("1.0", "строка журнала")
    text.configure(state="disabled")

    clipboard.select_all(text)

    assert text.get("sel.first", "sel.last") == "строка журнала"


# ----------------------------------------------------------------------
def test_shortcuts_are_installed(root):
    assert not root.bind_all("<Control-KeyPress>")

    clipboard.install_shortcuts(root)

    assert root.bind_all("<Control-KeyPress>")


def test_context_menu_is_attached(root):
    entry = ttk.Entry(root)
    entry.pack()
    assert not entry.bind("<Button-3>")

    menu = clipboard.attach_context_menu(entry)

    assert entry.bind("<Button-3>")
    labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) == "command"]
    assert labels == ["Вырезать", "Копировать", "Вставить", "Выделить всё"]


def test_read_only_menu_has_no_editing_items(root):
    text = tk.Text(root, state="disabled")
    text.pack()

    menu = clipboard.attach_context_menu(text, editable=False)

    labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) == "command"]
    assert labels == ["Копировать", "Выделить всё"]


def test_clipboard_text_helper(root):
    put_in_clipboard(root, "  значение\n")
    assert clipboard.clipboard_text(root) == "значение"


def test_clipboard_text_on_empty_buffer(root):
    root.clipboard_clear()
    assert clipboard.clipboard_text(root) == ""


# ----------------------------------------------------------------------
def test_paste_button_fills_key_field(root):
    from elevenlabs_voiceover.gui import App
    from elevenlabs_voiceover.logging_setup import setup_logging

    setup_logging()
    app = App(root)
    try:
        put_in_clipboard(root, "sk_from_clipboard_9876543210\n")

        app._paste_key()

        assert app.var_api_key.get() == "sk_from_clipboard_9876543210"
        # После вставки ключ показывается, чтобы было видно, что попало в поле.
        assert app.var_show_key.get() is True
        assert app.entry_key.cget("show") == ""
    finally:
        app.state.close()


def test_every_input_field_gets_context_menu(root):
    from elevenlabs_voiceover.gui import App, _all_widgets
    from elevenlabs_voiceover.logging_setup import setup_logging

    setup_logging()
    app = App(root)
    try:
        inputs = [w for w in _all_widgets(root) if isinstance(w, (tk.Entry, tk.Text))]
        assert len(inputs) >= 5

        without_menu = [str(w) for w in inputs if not w.bind("<Button-3>")]
        assert without_menu == []
    finally:
        app.state.close()
