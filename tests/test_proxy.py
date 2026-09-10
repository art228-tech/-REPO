"""Прокси до Telegram.

В России api.telegram.org заблокирован. VPN в режиме «Proxy» не помогает: он
уводит браузер, а Python идёт мимо. Поэтому адрес прокси задаётся в настройках.

Приносят его в том виде, в каком дал продавец — то с протоколом, то без, то с
логином через двоеточие. Разбирать это должна программа: иначе человек получит
невнятную ошибку соединения и решит, что дело в боте.
"""
from __future__ import annotations

from videobot import config, report


def test_empty_stays_empty():
    assert config.proxy("") == ""
    assert config.proxy("   ") == ""


def test_bare_address_gets_a_protocol():
    """Без протокола клиент адрес не примет, а человек его обычно не пишет."""
    assert config.proxy("1.2.3.4:1080") == "http://1.2.3.4:1080"


def test_four_parts_are_read_as_address_and_login():
    """Ходовая запись у продавцов прокси: адрес:порт:логин:пароль."""
    assert config.proxy("1.2.3.4:1080:user:pass") == "http://user:pass@1.2.3.4:1080"


def test_full_address_is_left_alone():
    for raw in ("socks5://u:p@1.2.3.4:1080", "http://1.2.3.4:8080"):
        assert config.proxy(raw) == raw


def test_report_hides_the_proxy_password():
    """Пароль от прокси — тоже чужой секрет, а отчёт уходит наружу."""
    hidden = report._proxy("socks5://user:secret@1.2.3.4:1080")

    assert "secret" not in hidden
    assert "1.2.3.4:1080" in hidden


def test_report_hides_the_password_in_the_colon_form():
    hidden = report._proxy("1.2.3.4:1080:user:secret")

    assert "secret" not in hidden
    assert "1.2.3.4:1080" in hidden


def test_report_keeps_an_address_without_a_password_readable():
    assert report._proxy("1.2.3.4:1080") == "1.2.3.4:1080"


def test_report_says_when_there_is_no_proxy():
    assert report._proxy("") == "не указан"
