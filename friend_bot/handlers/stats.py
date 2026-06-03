"""Статистика приветок."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from database import get_db
from handlers.start import is_admin
from keyboards.constructor_kb import back_to, stats_menu

router = Router(name="stats")


async def _stats_text(bot_id: int, filter_kind: str) -> str:
    """filter_kind: 'all' | 'prem' | 'dead' | 'alive'."""
    db = get_db()
    users = await db.list_users(bot_id)
    steps = await db.list_steps(bot_id)

    # Применяем фильтр
    if filter_kind == "prem":
        users_f = [u for u in users if u["is_premium"]]
        title = "⭐️ Премиум-юзеры"
    elif filter_kind == "dead":
        users_f = [u for u in users if not u["is_alive"]]
        title = "🪦 Мёртвые (заблокировавшие)"
    elif filter_kind == "alive":
        users_f = [u for u in users if u["is_alive"]]
        title = "🟢 Живые"
    else:
        users_f = list(users)
        title = "👥 Все юзеры"

    total = len(users_f)
    if total == 0:
        return f"<b>{title}</b>\n\nПока нет пользователей."

    n_alive = sum(1 for u in users_f if u["is_alive"])
    n_dead = total - n_alive
    n_premium = sum(1 for u in users_f if u["is_premium"])
    n_completed = sum(1 for u in users_f if u["completed"])

    text = (
        f"<b>{title}</b>\n\n"
        f"Всего: <b>{total}</b>\n"
        f"🟢 Живых: {n_alive} ({n_alive*100//total}%)\n"
        f"🪦 Мёртвых: {n_dead} ({n_dead*100//total}%)\n"
        f"⭐️ Премиум: {n_premium} ({n_premium*100//total}%)\n"
        f"🏁 Полностью прошли сценарий: {n_completed} ({n_completed*100//total}%)\n"
    )

    if steps:
        text += "\n<b>📜 Прохождение по шагам:</b>\n"
        type_emoji = {"roulette": "🎰", "op": "📢", "message": "💬"}
        # Один SQL — соберём прохождения по фильтру
        user_ids = [u["id"] for u in users_f]
        if user_ids:
            placeholders = ",".join("?" * len(user_ids))
            for s in steps:
                cur = await db.conn.execute(
                    f"SELECT COUNT(DISTINCT user_id) FROM step_completions "
                    f"WHERE step_id = ? AND user_id IN ({placeholders})",
                    [s["id"]] + user_ids,
                )
                cnt = (await cur.fetchone())[0]
                pct = cnt * 100 // total if total else 0
                emoji = type_emoji.get(s["step_type"], "·")
                text += f"{s['step_order']+1}. {emoji} {s['step_type']}: {cnt}/{total} ({pct}%)\n"

    return text


@router.callback_query(F.data.startswith("stat:"))
async def cb_stats(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.clear()
    bot_id = int(cb.data.split(":")[1])
    text = await _stats_text(bot_id, "all")
    await cb.message.edit_text(text, reply_markup=stats_menu(bot_id))
    await cb.answer()


@router.callback_query(F.data.startswith("st_all:"))
async def cb_stats_all(cb: CallbackQuery) -> None:
    bot_id = int(cb.data.split(":")[1])
    text = await _stats_text(bot_id, "all")
    await cb.message.edit_text(text, reply_markup=stats_menu(bot_id))
    await cb.answer()


@router.callback_query(F.data.startswith("st_prem:"))
async def cb_stats_prem(cb: CallbackQuery) -> None:
    bot_id = int(cb.data.split(":")[1])
    text = await _stats_text(bot_id, "prem")
    await cb.message.edit_text(text, reply_markup=stats_menu(bot_id))
    await cb.answer()


@router.callback_query(F.data.startswith("st_dead:"))
async def cb_stats_dead(cb: CallbackQuery) -> None:
    bot_id = int(cb.data.split(":")[1])
    text = await _stats_text(bot_id, "dead")
    await cb.message.edit_text(text, reply_markup=stats_menu(bot_id))
    await cb.answer()


@router.callback_query(F.data.startswith("st_refs:"))
async def cb_stats_refs(cb: CallbackQuery) -> None:
    bot_id = int(cb.data.split(":")[1])
    db = get_db()
    refs = await db.list_ref_links(bot_id)
    users = await db.list_users(bot_id)
    steps = await db.list_steps(bot_id)
    if not refs:
        await cb.message.edit_text(
            "🔗 Реф-ссылок ещё нет. Создай их в разделе «Реф-ссылки».",
            reply_markup=stats_menu(bot_id),
        )
        await cb.answer()
        return

    # Группируем юзеров по ref_link_id
    by_ref: dict[int, list] = {}
    for u in users:
        if u["ref_link_id"]:
            by_ref.setdefault(u["ref_link_id"], []).append(u)

    text = f"<b>🔗 Статистика по реф-ссылкам</b>\n"
    text += f"Всего юзеров: {len(users)}, по ссылкам: {sum(len(v) for v in by_ref.values())}\n\n"
    type_emoji = {"roulette": "🎰", "op": "📢", "message": "💬"}
    for r in refs:
        ul = by_ref.get(r["id"], [])
        total = len(ul)
        text += f"<b>{r['name'] or r['code']}</b> (<code>ref_{r['code']}</code>)\n"
        text += f"   Всего: {total}\n"
        if total > 0:
            n_alive = sum(1 for u in ul if u["is_alive"])
            n_prem = sum(1 for u in ul if u["is_premium"])
            n_done = sum(1 for u in ul if u["completed"])
            text += (
                f"   🟢 {n_alive} | 🪦 {total-n_alive} | "
                f"⭐ {n_prem} | 🏁 {n_done}\n"
            )
            # По шагам (кратко)
            uids = [u["id"] for u in ul]
            placeholders = ",".join("?" * len(uids))
            for s in steps[:5]:
                cur = await db.conn.execute(
                    f"SELECT COUNT(DISTINCT user_id) FROM step_completions "
                    f"WHERE step_id = ? AND user_id IN ({placeholders})",
                    [s["id"]] + uids,
                )
                cnt = (await cur.fetchone())[0]
                pct = cnt * 100 // total
                e = type_emoji.get(s["step_type"], "·")
                text += f"   {s['step_order']+1}.{e} {pct}%\n"
        text += "\n"

    if len(text) > 4000:
        text = text[:3900] + "\n\n…(обрезано)"
    await cb.message.edit_text(text, reply_markup=stats_menu(bot_id))
    await cb.answer()
