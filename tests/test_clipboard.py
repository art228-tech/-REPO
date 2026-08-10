import pytest

# Модуль работы с буфером — часть графического слоя и тянет tkinter. Там, где
# его нет, тесты пропускаем, а не роняем сбор всего набора.
pytest.importorskip("tkinter")

from elevenlabs_voiceover.clipboard import resolve_action


# ----------------------------------------------------------------------
# Латинская раскладка: Tk справляется сам, дублировать действие нельзя.
# ----------------------------------------------------------------------
def test_latin_v_is_paste_already_handled():
    assert resolve_action("v", 86, "win32") == ("paste", True)


def test_latin_c_is_copy_already_handled():
    assert resolve_action("c", 67, "win32") == ("copy", True)


def test_latin_x_is_cut_already_handled():
    assert resolve_action("x", 88, "win32") == ("cut", True)


def test_latin_a_is_select_all():
    assert resolve_action("a", 65, "win32") == ("select_all", True)


def test_uppercase_keysym_is_recognised():
    # При зажатом Shift Tk присылает заглавную букву.
    assert resolve_action("V", 86, "win32") == ("paste", True)


# ----------------------------------------------------------------------
# Русская раскладка: keysym приходит кириллический, спасает код клавиши.
# ----------------------------------------------------------------------
def test_cyrillic_layout_paste_on_windows():
    # Та же физическая клавиша V, но раскладка русская: Tk видит «м».
    assert resolve_action("Cyrillic_em", 86, "win32") == ("paste", False)


def test_cyrillic_layout_copy_on_windows():
    assert resolve_action("Cyrillic_es", 67, "win32") == ("copy", False)


def test_cyrillic_layout_cut_on_windows():
    assert resolve_action("Cyrillic_che", 88, "win32") == ("cut", False)


def test_cyrillic_layout_select_all_on_windows():
    assert resolve_action("Cyrillic_ef", 65, "win32") == ("select_all", False)


def test_cyrillic_layout_paste_on_x11():
    assert resolve_action("Cyrillic_em", 55, "linux") == ("paste", False)


def test_unknown_platform_falls_back_to_x11_codes():
    assert resolve_action("Cyrillic_em", 55, "freebsd14") == ("paste", False)


# ----------------------------------------------------------------------
def test_unrelated_key_gives_no_action():
    assert resolve_action("Cyrillic_ya", 90, "win32") == (None, False)


def test_arrow_key_gives_no_action():
    assert resolve_action("Left", 37, "win32") == (None, False)


def test_empty_keysym_is_safe():
    assert resolve_action("", 0, "win32") == (None, False)


def test_none_keysym_is_safe():
    assert resolve_action(None, 0, "win32") == (None, False)


def test_windows_and_x11_codes_do_not_collide():
    # Код 55 на Windows — это цифра 7, а не вставка.
    assert resolve_action("Cyrillic_em", 55, "win32") == (None, False)
