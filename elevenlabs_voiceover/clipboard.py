"""Буфер обмена, работающий при любой раскладке клавиатуры.

Tk привязывает Ctrl+C, Ctrl+V и Ctrl+X к латинским буквам. При русской
раскладке та же физическая клавиша приходит как Ctrl+М, привязка не совпадает,
и вставка молча не срабатывает. Контекстного меню по правой кнопке у полей ввода
в Tk тоже нет, так что запасного пути у человека не остаётся.

Здесь обе дыры закрываются: сочетания разбираются по коду физической клавиши,
а к полям добавляется меню по правой кнопке.
"""

from __future__ import annotations

import sys
import tkinter as tk
from typing import Optional, Tuple

from .logging_setup import get_logger

log = get_logger("clipboard")

#: Латинские буквы, по которым Tk узнаёт сочетание сам.
_LATIN = {"a": "select_all", "c": "copy", "v": "paste", "x": "cut"}

#: Коды физических клавиш: от раскладки не зависят.
_KEYCODES = {
    "win32": {65: "select_all", 67: "copy", 86: "paste", 88: "cut"},
    "x11": {38: "select_all", 54: "copy", 55: "paste", 53: "cut"},
}


def resolve_action(keysym: str, keycode: int, platform: str = sys.platform) -> Tuple[Optional[str], bool]:
    """Определить действие с буфером по нажатой клавише.

    Возвращает пару: название действия и признак того, что раскладка латинская
    и Tk уже обработал сочетание самостоятельно.
    """
    key = (keysym or "").lower()
    if key in _LATIN:
        return _LATIN[key], True

    table = _KEYCODES.get(platform) or _KEYCODES["x11"]
    return table.get(keycode), False


# ----------------------------------------------------------------------
def _drop_selection(widget) -> None:
    try:
        widget.delete("sel.first", "sel.last")
    except tk.TclError:
        pass


def paste(widget) -> str:
    try:
        text = widget.clipboard_get()
    except tk.TclError:
        # Буфер пуст либо содержит не текст.
        return "break"
    if not text:
        return "break"

    if isinstance(widget, tk.Entry):
        # Поле однострочное: перевод строки в конце скопированного ключа —
        # обычное дело, и внутрь его пускать нельзя.
        text = text.replace("\r", " ").replace("\n", " ").strip()
        _drop_selection(widget)
        widget.insert("insert", text)
    elif isinstance(widget, tk.Text):
        _drop_selection(widget)
        widget.insert("insert", text)
    return "break"


def copy(widget) -> str:
    try:
        text = widget.selection_get()
    except tk.TclError:
        return "break"
    if text:
        widget.clipboard_clear()
        widget.clipboard_append(text)
    return "break"


def cut(widget) -> str:
    copy(widget)
    _drop_selection(widget)
    return "break"


def select_all(widget) -> str:
    if isinstance(widget, tk.Entry):
        widget.select_range(0, "end")
        widget.icursor("end")
    elif isinstance(widget, tk.Text):
        widget.tag_add("sel", "1.0", "end-1c")
        widget.mark_set("insert", "1.0")
    return "break"


_ACTIONS = {"paste": paste, "copy": copy, "cut": cut, "select_all": select_all}


# ----------------------------------------------------------------------
def install_shortcuts(root: tk.Misc) -> None:
    """Включить Ctrl+C, Ctrl+V, Ctrl+X и Ctrl+A при любой раскладке."""

    def handle(event):
        action, latin_layout = resolve_action(event.keysym, event.keycode)
        if action is None:
            return None

        # Ctrl+A перехватываем всегда: в Tk эта клавиша по умолчанию переносит
        # курсор в начало строки, а не выделяет всё, как ждут на Windows.
        if action == "select_all":
            return _ACTIONS[action](event.widget)

        if latin_layout:
            # Tk уже вставил или скопировал сам, второй раз не нужно.
            return None

        return _ACTIONS[action](event.widget)

    root.bind_all("<Control-KeyPress>", handle)


def attach_context_menu(widget: tk.Misc, *, editable: bool = True) -> tk.Menu:
    """Добавить полю меню по правой кнопке мыши."""
    menu = tk.Menu(widget, tearoff=0)
    if editable:
        menu.add_command(label="Вырезать", command=lambda: cut(widget))
    menu.add_command(label="Копировать", command=lambda: copy(widget))
    if editable:
        menu.add_command(label="Вставить", command=lambda: paste(widget))
    menu.add_separator()
    menu.add_command(label="Выделить всё", command=lambda: select_all(widget))

    def show(event):
        widget.focus_set()
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    widget.bind("<Button-3>", show)
    widget.bind("<Button-2>", show)
    return menu


def clipboard_text(widget: tk.Misc) -> str:
    """Содержимое буфера обмена одной строкой, пустая строка при неудаче."""
    try:
        return (widget.clipboard_get() or "").replace("\r", " ").replace("\n", " ").strip()
    except tk.TclError:
        return ""
