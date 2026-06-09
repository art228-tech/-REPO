"""Проверка подписки пользователя на каналы-спонсоры."""
from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError


SUBSCRIBED_STATUSES = {"creator", "administrator", "member", "restricted"}


async def is_subscribed(bot: Bot, channel_id: int, user_id: int) -> bool:
    """Проверяет, подписан ли пользователь на канал.
    Бот должен быть админом в этом канале.
    Если что-то не так — возвращает False.
    """
    if not channel_id:
        return False
    try:
        member = await bot.get_chat_member(channel_id, user_id)
        return member.status in SUBSCRIBED_STATUSES
    except (TelegramBadRequest, TelegramForbiddenError):
        return False
    except Exception as e:
        print(f"[is_subscribed] {e}")
        return False


async def check_all_sponsors(
    bot: Bot, sponsors: list[dict], user_id: int
) -> list[dict]:
    """Возвращает список НЕпройденных спонсоров (тех, которых юзер ещё не прошёл).
    Спонсоры с check=False всегда «непройдены» (т.е. всегда показываются)."""
    not_subscribed: list[dict] = []
    for sp in sponsors:
        if not sp.get("check"):
            # Просто показывается, не проверяется — всегда «не пройден» (т.е. показывается)
            not_subscribed.append(sp)
            continue
        cid = sp.get("channel_id")
        if not cid:
            not_subscribed.append(sp)
            continue
        ok = await is_subscribed(bot, int(cid), user_id)
        if not ok:
            not_subscribed.append(sp)
    return not_subscribed


async def get_unsubscribed_check_required(
    bot: Bot, sponsors: list[dict], user_id: int, *, bot_id: int | None = None
) -> list[dict]:
    """Возвращает список обязательных спонсоров, которых юзер ещё не «прошёл».
    Прошёл = подписан, либо (если канал «по заявкам») подал заявку."""
    from database import get_db
    db = get_db() if bot_id is not None else None
    res: list[dict] = []
    for sp in sponsors:
        if not sp.get("check"):
            continue
        cid = sp.get("channel_id")
        if not cid:
            continue
        # Подписан?
        if await is_subscribed(bot, int(cid), user_id):
            continue
        # Канал «по заявкам» и заявка есть?
        if sp.get("request_mode") and db is not None:
            if await db.has_pending_join_request(bot_id, int(cid), user_id):
                continue
        res.append(sp)
    return res
