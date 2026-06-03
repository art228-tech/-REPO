"""Проверка прав приветки в канале-спонсоре."""
from __future__ import annotations

from typing import Literal
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError


SponsorCheckResult = dict  # {"ok": bool, "reason": str | None, "details": dict}


async def check_sponsor_access(
    bot: Bot,
    channel_id: int,
    *,
    require_invite_users: bool = False,
) -> SponsorCheckResult:
    """Проверяет что приветка имеет доступ к каналу-спонсору.

    Возвращает dict:
      ok=True/False
      reason — текстовое описание проблемы (если ok=False)
      details — словарь с status, can_invite_users и т.п.
    """
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(channel_id, me.id)
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "chat not found" in msg:
            return {"ok": False, "reason": "канал не найден (неверный chat_id или приветка не добавлена)", "details": {}}
        if "member list is inaccessible" in msg or "user_not_participant" in msg:
            return {"ok": False, "reason": "приветка не в канале — добавь её админом", "details": {}}
        return {"ok": False, "reason": f"Telegram: {e}", "details": {}}
    except TelegramForbiddenError:
        return {"ok": False, "reason": "приветка забанена или нет доступа к каналу", "details": {}}
    except Exception as e:
        return {"ok": False, "reason": f"ошибка: {e}", "details": {}}

    status = getattr(member, "status", "unknown")
    can_invite = bool(getattr(member, "can_invite_users", False))
    details = {"status": status, "can_invite_users": can_invite}

    if status not in ("administrator", "creator"):
        return {"ok": False, "reason": f"приветка не админ канала (статус: {status})", "details": details}

    if require_invite_users and not can_invite and status != "creator":
        return {"ok": False, "reason": "у приветки нет права «Приглашать пользователей через ссылки»", "details": details}

    return {"ok": True, "reason": None, "details": details}


async def check_invite_link(bot: Bot, link: str, channel_id: int) -> SponsorCheckResult:
    """Проверяет ссылку-приглашение: что она ведёт к нужному каналу
    и не отозвана. Для t.me/joinchat/... и t.me/+... через getChat невозможно,
    поэтому ограничиваемся форматом.
    """
    if not link:
        return {"ok": False, "reason": "пустая ссылка", "details": {}}
    if not (link.startswith("http://") or link.startswith("https://") or link.startswith("tg://")):
        return {"ok": False, "reason": "ссылка не похожа на URL (нужна https://t.me/...)", "details": {}}
    return {"ok": True, "reason": None, "details": {}}
