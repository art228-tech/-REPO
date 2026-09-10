"""Повторный запуск бота кнопкой.

Роутеры в aiogram привязываются к диспетчеру навсегда. Пока диспетчер собирался
на каждый запуск, вторая попытка обрывалась с «Router is already attached», а
остановить и снова запустить бота кнопкой — обычное дело: поменяли токен,
подождали интернет, просто перезапустили.

Собрать диспетчер здесь можно ровно один раз на весь прогон — по той же
причине, из-за которой он и кэшируется. Поэтому фикстура одна на модуль.
"""
from __future__ import annotations

import pytest

from videobot.config import Settings
from videobot.guard import Guard
from videobot.tg import app


@pytest.fixture(scope="module")
def dispatcher(tmp_path_factory):
    from videobot.db import Base

    app.forget_dispatcher()
    base = Base(tmp_path_factory.mktemp("бот") / "bot.sqlite3")
    settings = Settings(token="1:a")
    made = app.dispatcher_for(base, settings, Guard(85, 30))
    yield made, base, settings


def test_second_start_gets_the_same_dispatcher(dispatcher):
    """Ровно та ошибка, из-за которой бот не запускался со второго раза."""
    made, base, settings = dispatcher
    again = app.dispatcher_for(base, settings, Guard(85, 30))

    assert again is made


def test_both_routers_are_in_place(dispatcher):
    made, _, _ = dispatcher

    assert len(made.sub_routers) == 2


def test_settings_are_shared_not_copied(dispatcher):
    """Токен меняют в окне уже после сборки диспетчера — он должен это увидеть."""
    made, base, settings = dispatcher
    settings.token = "2:b"

    again = app.dispatcher_for(base, settings, Guard(85, 30))
    assert again is made
