"""Регистрация роутеров."""
from aiogram import Dispatcher

from handlers import common, helpers_h, channels, tasks, post_edit, posting


def register_all(dp: Dispatcher) -> None:
    dp.include_router(common.router)
    dp.include_router(helpers_h.router)
    dp.include_router(channels.router)
    dp.include_router(tasks.router)
    dp.include_router(post_edit.router)
    dp.include_router(posting.router)
