"""Регистрация всех роутеров админ-бота."""
from aiogram import Dispatcher

from . import start, add_bot, bot_menu, scenario_edit, step_create, stats, broadcast, refs, sponsor_edit


def register_all(dp: Dispatcher) -> None:
    dp.include_router(start.router)
    dp.include_router(add_bot.router)
    dp.include_router(bot_menu.router)
    dp.include_router(scenario_edit.router)
    dp.include_router(step_create.router)
    dp.include_router(stats.router)
    dp.include_router(broadcast.router)
    dp.include_router(refs.router)
    dp.include_router(sponsor_edit.router)
