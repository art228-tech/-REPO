"""
Statistics for a welcome bot: users, conversion per OP step, top ref links.
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select, func, distinct

from shared.db import db
from shared.models import BotUser, ScenarioStep, UserStepCompletion, WelcomeBot
from constructor_bot.keyboards.menus import back_kb

router = Router()


@router.callback_query(F.data.startswith("stats:"))
async def cb_stats(callback: CallbackQuery):
    bot_id = int(callback.data.split(":")[1])

    async with db() as session:
        bot = await session.get(WelcomeBot, bot_id)

        # Total users
        total = (await session.execute(
            select(func.count(BotUser.id)).where(BotUser.bot_id == bot_id)
        )).scalar() or 0

        # Per-step completions
        steps_result = await session.execute(
            select(ScenarioStep)
            .where(ScenarioStep.bot_id == bot_id)
            .order_by(ScenarioStep.position)
        )
        steps = steps_result.scalars().all()

        step_stats = []
        for step in steps:
            count = (await session.execute(
                select(func.count(distinct(UserStepCompletion.bot_user_id)))
                .join(BotUser, UserStepCompletion.bot_user_id == BotUser.id)
                .where(
                    BotUser.bot_id == bot_id,
                    UserStepCompletion.step_id == step.id
                )
            )).scalar() or 0
            pct = round(count / total * 100, 1) if total > 0 else 0
            step_stats.append((step, count, pct))

        # Top referral links
        ref_result = await session.execute(
            select(BotUser.join_ref, func.count(BotUser.id).label("cnt"))
            .where(BotUser.bot_id == bot_id, BotUser.join_ref.isnot(None))
            .group_by(BotUser.join_ref)
            .order_by(func.count(BotUser.id).desc())
            .limit(10)
        )
        top_refs = ref_result.all()

    # Build text
    icons = {"message": "💬", "op": "🔒", "wait": "⏳"}
    lines = [f"📊 <b>Статистика: {bot.name}</b>\n", f"👥 Всего пользователей: <b>{total}</b>\n"]

    if step_stats:
        lines.append("📈 <b>Конверсия по шагам:</b>")
        for step, count, pct in step_stats:
            icon = icons.get(step.step_type, "❓")
            bar = _progress_bar(pct)
            lines.append(f"{icon} Шаг {step.position + 1} ({step.step_type}): {count} ({pct}%) {bar}")

    if top_refs:
        lines.append("\n🔗 <b>Топ ссылок (join_ref):</b>")
        for ref, cnt in top_refs:
            pct = round(cnt / total * 100, 1) if total > 0 else 0
            lines.append(f"  • <code>{ref}</code> → {cnt} ({pct}%)")

    text = "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=back_kb(f"bot_menu:{bot_id}"))
    await callback.answer()


def _progress_bar(pct: float, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    return "▓" * filled + "░" * (width - filled)
