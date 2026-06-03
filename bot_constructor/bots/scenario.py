"""
Движок сценариев.

Управляет прохождением сценария для каждого пользователя:
- отправка текущего шага
- планирование удаления старого сообщения
- планирование дублирования при застревании
- продвижение к следующему шагу
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup

from config import WEBAPP_URL
from database import DB, get_db, now
from utils.checker import get_unsubscribed_check_required
from utils.helpers import (
    build_inline_keyboard,
    remove_keyboard,
    reply_keyboard,
    safe_delete_message,
    send_step_message,
)

log = logging.getLogger("scenario")


class ScenarioEngine:
    """Один экземпляр на процесс. Хранит активные asyncio-задачи."""

    def __init__(self) -> None:
        # ключ: (bot_id, user_id) — значение: список задач
        self._dup_tasks: dict[tuple[int, int], asyncio.Task] = {}
        self._del_tasks: dict[tuple[int, int], asyncio.Task] = {}
        self._delay_tasks: dict[tuple[int, int], asyncio.Task] = {}
        self._roulette_timeout_tasks: dict[tuple[int, int], asyncio.Task] = {}

    # ----------------- ПУБЛИЧНОЕ API -----------------

    async def start_or_restart(self, bot: Bot, bot_record, user) -> None:
        """Запускает сценарий с самого начала (или перезапускает, если уже идёт)."""
        db = get_db()
        # Отменяем все активные задачи
        self._cancel_all_for(bot_record["id"], user["id"])
        # Сбрасываем прогресс
        await db.reset_user_progress(user["id"])

        # Учитываем join_delay
        if bot_record["join_delay"] and bot_record["join_delay"] > 0:
            await self._schedule_delayed_start(
                bot, bot_record, user["id"], bot_record["join_delay"]
            )
        else:
            await self._send_step_to_user(bot, bot_record, user["id"], step_order=0)

    async def advance(self, bot: Bot, bot_record, user_id: int) -> None:
        """Продвигает пользователя на следующий шаг."""
        db = get_db()
        user = await db.get_user(user_id)
        if not user:
            return

        # Отменяем дублирование и таймеры рулетки
        self._cancel_dup(bot_record["id"], user_id)
        self._cancel_roulette_timeout(bot_record["id"], user_id)

        next_order = (user["current_step_order"] or 0) + 1
        await db.update_user(
            user_id, current_step_order=next_order, duplicate_count=0,
            awaiting_user_msg=0, awaiting_kb_text=None,
        )
        await self._send_step_to_user(bot, bot_record, user_id, step_order=next_order)

    async def handle_callback(
        self, bot: Bot, bot_record, user_id: int, action: str, payload: dict
    ) -> tuple[bool, Optional[str]]:
        """
        Обрабатывает callback-кнопки на текущем шаге.
        action: 'check_op' — проверка подписки
        Возвращает (продвинуть_дальше, ответ_для_алерта)
        """
        db = get_db()
        user = await db.get_user(user_id)
        if not user:
            return False, None
        step = await db.get_step_by_order(bot_record["id"], user["current_step_order"])
        if not step or step["step_type"] != "op":
            return False, None

        cfg = json.loads(step["config"])
        sponsors = cfg.get("sponsors", [])
        not_ok = await get_unsubscribed_check_required(bot, sponsors, user["tg_id"])
        if not_ok:
            return False, "❌ Ты подписался не на все каналы. Подпишись и нажми «Проверить»."
        return True, "✅ Отлично! Все подписки на месте."

    async def handle_roulette_done(
        self, bot: Bot, bot_record, user_tg_id: int, win_amount: int = 5000
    ) -> None:
        """Вызывается из webapp когда юзер забрал приз (или истекли 5 сек)."""
        db = get_db()
        user = await db.get_user_by_tg(bot_record["id"], user_tg_id)
        if not user:
            return
        step = await db.get_step_by_order(bot_record["id"], user["current_step_order"])
        if not step or step["step_type"] != "roulette":
            return
        # Записываем приз
        await db.record_roulette_win(user["id"], step["id"], win_amount)
        await db.record_step_completion(user["id"], step["id"])
        # Двигаем дальше
        await self.advance(bot, bot_record, user["id"])

    async def handle_message_from_user(
        self, bot: Bot, bot_record, user_id: int, text: Optional[str]
    ) -> bool:
        """
        Если шаг ждёт сообщение от юзера — продвигает дальше.
        Возвращает True если продвинули, False если не ждали.
        """
        db = get_db()
        user = await db.get_user(user_id)
        if not user or not user["awaiting_user_msg"]:
            return False
        step = await db.get_step_by_order(bot_record["id"], user["current_step_order"])
        if not step or step["step_type"] != "message":
            return False
        cfg = json.loads(step["config"])
        # Если ждём именно кнопку клавы — текст должен совпасть
        kb_text = user["awaiting_kb_text"]
        if kb_text and text != kb_text:
            return False
        await db.record_step_completion(user["id"], step["id"])
        await self.advance(bot, bot_record, user_id)
        return True

    # ----------------- ВНУТРЕННЕЕ -----------------

    async def _schedule_delayed_start(
        self, bot: Bot, bot_record, user_id: int, delay: int
    ) -> None:
        key = (bot_record["id"], user_id)
        old = self._delay_tasks.pop(key, None)
        if old:
            old.cancel()
        task = asyncio.create_task(self._delayed_start_runner(bot, bot_record, user_id, delay))
        self._delay_tasks[key] = task

    async def _delayed_start_runner(self, bot: Bot, bot_record, user_id: int, delay: int) -> None:
        try:
            await asyncio.sleep(delay)
            await self._send_step_to_user(bot, bot_record, user_id, step_order=0)
        except asyncio.CancelledError:
            pass

    async def _send_step_to_user(
        self, bot: Bot, bot_record, user_id: int, *, step_order: int, is_duplicate: bool = False
    ) -> None:
        db = get_db()
        user = await db.get_user(user_id)
        if not user:
            return
        step = await db.get_step_by_order(bot_record["id"], step_order)
        if not step:
            # Сценарий закончился
            await db.update_user(user_id, completed=1, current_step_order=step_order)
            # Удаляем старое сообщение по таймеру тоже
            await self._schedule_delete_old(bot, bot_record, user)
            return

        # Перед отправкой удаляем старое сообщение по таймеру (если не дубль)
        if not is_duplicate:
            await self._schedule_delete_old(bot, bot_record, user)

        cfg = json.loads(step["config"])
        step_type = step["step_type"]

        msg_id: Optional[int] = None

        if step_type == "roulette":
            msg_id = await self._send_roulette_step(bot, bot_record, user, step, cfg)
        elif step_type == "op":
            msg_id = await self._send_op_step(bot, bot_record, user, step, cfg)
        elif step_type == "message":
            msg_id = await self._send_message_step(bot, bot_record, user, step, cfg)
        else:
            log.warning("Unknown step_type: %s", step_type)
            return

        if msg_id is None:
            # отправка не удалась (например, юзер заблокировал)
            return
        if msg_id == -1:
            # маркер: шаг сам автопрошёл (например, ОП-скип). advance уже вызван.
            return

        # Обновляем user
        await db.update_user(
            user_id,
            current_step_order=step_order,
            last_message_id=msg_id,
            last_message_chat_id=user["tg_id"],
            last_sent_at=now(),
        )

        # Планируем дублирование, если шаг не «таймер»; при is_duplicate
        # задача уже работает — не пересоздаём её
        if not is_duplicate:
            await self._schedule_duplicate(bot, bot_record, user_id, step)

        # Если шаг — таймер на следующий, планируем переход
        if step_type == "message" and cfg.get("wait_mode") == "timer":
            timer = int(cfg.get("wait_timer", 0))
            if timer > 0:
                async def _timer_advance() -> None:
                    try:
                        await asyncio.sleep(timer)
                        # Записываем прохождение
                        await get_db().record_step_completion(user_id, step["id"])
                        await self.advance(bot, bot_record, user_id)
                    except asyncio.CancelledError:
                        pass
                # Используем dup_tasks слот для этой задачи (она тоже будет отменена при advance)
                key = (bot_record["id"], user_id)
                old = self._dup_tasks.pop(key, None)
                if old:
                    old.cancel()
                self._dup_tasks[key] = asyncio.create_task(_timer_advance())
                return

        # Если ждём сообщение от юзера — устанавливаем флаг
        if step_type == "message" and cfg.get("wait_mode") == "user_message":
            kb_text = cfg.get("keyboard_text") or None
            await db.update_user(user_id, awaiting_user_msg=1, awaiting_kb_text=kb_text)

    async def _send_roulette_step(self, bot, bot_record, user, step, cfg) -> Optional[int]:
        text = cfg.get("text") or "🎰 Крути рулетку и забери приз!"
        photo = cfg.get("photo_file_id")
        button_text = cfg.get("button_text") or "🎰 Крутить рулетку"
        button_color = cfg.get("button_color") or "default"
        web_app_url = (
            f"{WEBAPP_URL}/roulette?bid={bot_record['id']}&sid={step['id']}"
            f"&uid={user['tg_id']}"
        )
        rows = [[{"text": button_text, "web_app": web_app_url, "color": button_color}]]
        markup = build_inline_keyboard(rows)
        try:
            return await send_step_message(
                bot, user["tg_id"], text=text, photo_file_id=photo, reply_markup=markup
            )
        except TelegramForbiddenError:
            await get_db().mark_user_dead(user["id"])
            return None

    async def _send_op_step(self, bot, bot_record, user, step, cfg) -> Optional[int]:
        text = cfg.get("text") or "📢 Подпишись на каналы спонсоров"
        photo = cfg.get("photo_file_id")
        sponsors = cfg.get("sponsors", [])
        check_btn_text = cfg.get("check_button_text") or "✅ Проверить"
        check_btn_color = cfg.get("check_button_color") or "green"

        # Спонсоры, которые надо показать (не подписан, или check=False)
        to_show: list[dict] = []
        for sp in sponsors:
            if not sp.get("check"):
                to_show.append(sp)
            else:
                from utils.checker import is_subscribed
                cid = sp.get("channel_id")
                if cid and await is_subscribed(bot, int(cid), user["tg_id"]):
                    continue
                to_show.append(sp)

        # Если все уже подписаны (или их вообще нет с check) — продвигаем дальше
        # но только если хотя бы один требовал check
        has_required = any(s.get("check") for s in sponsors)
        if has_required and not any(s.get("check") for s in to_show):
            await get_db().record_step_completion(user["id"], step["id"])
            await self.advance(bot, bot_record, user["id"])
            return -1  # маркер: ничего не отправляем, перешли дальше

        # Формируем кнопки в 2 столбика
        sponsor_buttons: list[dict] = []
        for sp in to_show:
            sponsor_buttons.append({
                "text": sp.get("button_text") or sp.get("title") or "Подписаться",
                "url": sp.get("link"),
                "color": sp.get("button_color") or "default",
            })
        rows: list[list[dict]] = []
        for i in range(0, len(sponsor_buttons), 2):
            rows.append(sponsor_buttons[i : i + 2])
        # Кнопка проверки
        rows.append([{
            "text": check_btn_text,
            "callback_data": f"op_check:{step['id']}",
            "color": check_btn_color,
        }])
        markup = build_inline_keyboard(rows)
        try:
            return await send_step_message(
                bot, user["tg_id"], text=text, photo_file_id=photo, reply_markup=markup
            )
        except TelegramForbiddenError:
            await get_db().mark_user_dead(user["id"])
            return None

    async def _send_message_step(self, bot, bot_record, user, step, cfg) -> Optional[int]:
        text = cfg.get("text")
        photo = cfg.get("photo_file_id")
        sticker = cfg.get("sticker_file_id")
        animation = cfg.get("animation_file_id")
        video = cfg.get("video_file_id")
        document = cfg.get("document_file_id")
        copy_from = cfg.get("copy_from")  # {chat_id, message_id}

        buttons = cfg.get("buttons", [])
        rows: list[list[dict]] = []
        for i in range(0, len(buttons), 2):
            rows.append(buttons[i : i + 2])
        markup = build_inline_keyboard(rows)

        keyboard_markup = None
        if cfg.get("wait_mode") == "user_message" and cfg.get("keyboard_text"):
            keyboard_markup = reply_keyboard(cfg["keyboard_text"])

        try:
            return await send_step_message(
                bot,
                user["tg_id"],
                text=text,
                photo_file_id=photo,
                sticker_file_id=sticker,
                animation_file_id=animation,
                video_file_id=video,
                document_file_id=document,
                copy_from=copy_from,
                reply_markup=markup,
                keyboard_markup=keyboard_markup,
            )
        except TelegramForbiddenError:
            await get_db().mark_user_dead(user["id"])
            return None

    async def _schedule_delete_old(self, bot: Bot, bot_record, user) -> None:
        if not user["last_message_id"] or not user["last_message_chat_id"]:
            return
        delay = bot_record["delete_timer"] or 10
        chat_id = user["last_message_chat_id"]
        msg_id = user["last_message_id"]
        key = (bot_record["id"], user["id"])
        old = self._del_tasks.pop(key, None)
        if old:
            old.cancel()

        async def _runner() -> None:
            try:
                await asyncio.sleep(delay)
                await safe_delete_message(bot, chat_id, msg_id)
            except asyncio.CancelledError:
                pass
        self._del_tasks[key] = asyncio.create_task(_runner())

    async def _schedule_duplicate(self, bot: Bot, bot_record, user_id: int, step) -> None:
        """Планируем дублирование, если юзер не продвинется за указанное время."""
        if step["step_type"] == "message":
            cfg = json.loads(step["config"])
            if cfg.get("wait_mode") == "timer":
                return  # таймер сам продвинет

        key = (bot_record["id"], user_id)
        old = self._dup_tasks.pop(key, None)
        if old:
            old.cancel()

        async def _runner() -> None:
            db = get_db()
            try:
                # Берём счётчик из БД, чтобы при пересоздании задачи
                # (после каждого _send_step_to_user) счётчик не обнулялся.
                u0 = await db.get_user(user_id)
                count = (u0["duplicate_count"] if u0 else 0) or 0
                base_delay = step["duplicate_after"] or 60
                inc = step["duplicate_increment"] or 0
                max_count = step["duplicate_max"] or 3
                while count < max_count:
                    delay = base_delay + inc * count
                    await asyncio.sleep(delay)
                    # Проверяем, что юзер всё ещё на этом шаге
                    user = await db.get_user(user_id)
                    if not user or not user["is_alive"]:
                        return
                    cur_step = await db.get_step_by_order(
                        bot_record["id"], user["current_step_order"]
                    )
                    if not cur_step or cur_step["id"] != step["id"]:
                        return
                    # Дублируем сообщение
                    count += 1
                    await db.update_user(user_id, duplicate_count=count)
                    # Удаляем старое
                    if user["last_message_id"]:
                        await safe_delete_message(
                            bot, user["last_message_chat_id"], user["last_message_id"]
                        )
                    await self._send_step_to_user(
                        bot, bot_record, user_id,
                        step_order=user["current_step_order"], is_duplicate=True,
                    )
                # Лимит достигнут — пропускаем шаг
                user = await db.get_user(user_id)
                if user and user["current_step_order"] == step["step_order"]:
                    # Запускаем advance отдельной задачей, потому что
                    # advance вызовет _cancel_dup, который отменит нас же.
                    asyncio.create_task(self.advance(bot, bot_record, user_id))
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.exception("duplicate runner error: %s", e)

        self._dup_tasks[key] = asyncio.create_task(_runner())

    def _cancel_dup(self, bot_id: int, user_id: int) -> None:
        key = (bot_id, user_id)
        task = self._dup_tasks.pop(key, None)
        if task:
            task.cancel()

    def _cancel_roulette_timeout(self, bot_id: int, user_id: int) -> None:
        key = (bot_id, user_id)
        task = self._roulette_timeout_tasks.pop(key, None)
        if task:
            task.cancel()

    def _cancel_all_for(self, bot_id: int, user_id: int) -> None:
        key = (bot_id, user_id)
        for d in (self._dup_tasks, self._del_tasks, self._delay_tasks, self._roulette_timeout_tasks):
            t = d.pop(key, None)
            if t:
                t.cancel()

    async def shutdown(self) -> None:
        """Отменяет все фоновые задачи."""
        for d in (self._dup_tasks, self._del_tasks, self._delay_tasks, self._roulette_timeout_tasks):
            for t in list(d.values()):
                t.cancel()
            d.clear()


# Singleton
_engine: Optional[ScenarioEngine] = None


def get_engine() -> ScenarioEngine:
    global _engine
    if _engine is None:
        _engine = ScenarioEngine()
    return _engine
