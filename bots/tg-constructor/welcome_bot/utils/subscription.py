"""
Check if a user is subscribed to (or has pending join request in) a channel.
"""
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError


async def check_subscription(bot: Bot, user_id: int, channel_id: int) -> bool:
    """
    Returns True if user is member, admin, creator, or has pending join request.
    Returns False if not subscribed.
    channel_id must be the numeric ID (negative for channels/groups).
    """
    try:
        member = await bot.get_chat_member(channel_id, user_id)
        status = member.status.value if hasattr(member.status, 'value') else str(member.status)
        return status in ("member", "administrator", "creator", "restricted")
    except TelegramBadRequest as e:
        # "USER_NOT_PARTICIPANT" or similar
        if "user not found" in str(e).lower() or "chat not found" in str(e).lower():
            return False
        # Could be pending join request - treat as subscribed
        if "member_status" in str(e).lower():
            return True
        return False
    except TelegramForbiddenError:
        # Bot not admin in channel - can't check, assume passed
        return True
    except Exception:
        return False
