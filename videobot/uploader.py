"""Заливка роликов в Telegram.

Загрузчик в окне программы только ставит ролик в очередь: пишет в базу путь к
файлу и данные из реестра автомонтажа. Заливает уже бот, из своего потока.

Так сделано, чтобы окно не зависело от бота: можно накидать роликов, когда
интернет лежит или бот остановлен, — они дождутся в очереди.

Ролик уходит в чат админа и тут же оттуда удаляется. От файла остаётся
идентификатор Telegram: по нему бот потом пересылает ролик человеку, и байты
идут между серверами Telegram, минуя этот компьютер. Удаление сообщения на
идентификатор не влияет — сам файл остаётся на серверах Telegram. Оригиналы при
этом никуда не деваются, они лежат у вас на диске.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile

from .db import Base
from .logs import get_logger

log = get_logger("заливка")

IDLE_S = 3.0

# Телеграм принимает от бота файл до 50 МБ. Проверяем заранее, чтобы вместо
# невнятной ошибки от API человек увидел, какой именно ролик слишком тяжёлый.
MAX_BYTES = 50 * 1024 * 1024


async def upload_one(bot: Bot, base: Base, row, chat_id: int) -> bool:
    path = Path(row["file_path"])
    if not path.is_file():
        base.mark_failed(row["id"], f"файл не найден: {path}")
        log.error("Ролик %s: файл не найден (%s)", row["name"], path)
        return False

    size = path.stat().st_size
    if size > MAX_BYTES:
        base.mark_failed(
            row["id"], f"файл {size / 1024 / 1024:.0f} МБ, а Telegram берёт до 50 МБ")
        log.error("Ролик %s: %.0f МБ — больше, чем принимает Telegram",
                  row["name"], size / 1024 / 1024)
        return False

    try:
        message = await bot.send_document(
            chat_id=chat_id,
            document=FSInputFile(path, filename=path.name),
            disable_notification=True,
            caption=f"хранилище: {row['name']}",
        )
    except TelegramAPIError as exc:
        base.mark_failed(row["id"], str(exc))
        log.error("Ролик %s не залился: %s", row["name"], exc)
        return False

    document = message.document or (message.video and message.video)
    if document is None:
        base.mark_failed(row["id"], "Telegram не вернул файл")
        log.error("Ролик %s: Telegram не вернул файл", row["name"])
        return False

    base.mark_ready(row["id"], document.file_id)
    log.info("Ролик %s залит (%.1f МБ)", row["name"], size / 1024 / 1024)

    try:
        await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
    except TelegramAPIError:
        # Не беда: идентификатор уже получен, сообщение просто останется в чате.
        log.debug("Сообщение хранилища удалить не вышло, останется в чате")
    return True


async def loop(bot: Bot, base: Base, guard) -> None:
    """Разбирает очередь, пока задачу не отменят."""
    while True:
        row = base.next_pending()
        if row is None:
            await asyncio.sleep(IDLE_S)
            continue

        admins = base.admin_ids()
        if not admins:
            # Заливать некуда: админа ещё нет. Ролики подождут в очереди.
            await asyncio.sleep(IDLE_S)
            continue

        await guard.wait_until_free()
        await upload_one(bot, base, row, admins[0])
        await asyncio.sleep(0.5)
