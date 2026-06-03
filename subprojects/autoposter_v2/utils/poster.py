"""Движок автопостинга v2: постит через бот-помощника, привязанного к каналу."""
from __future__ import annotations

import asyncio
import json
import logging
import time

from aiogram.exceptions import TelegramUnauthorizedError

from database import get_db
from utils.helpers import send_post
from utils.manager import get_manager

log = logging.getLogger("poster")


class PosterEngine:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
            log.info("PosterEngine запущен")

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(5)
                await self._tick()
                await self._process_deletes()
            except asyncio.CancelledError:
                return
            except Exception as e:
                log.exception("poster loop error: %s", e)

    async def _tick(self) -> None:
        db = get_db()
        now = int(time.time())
        states = await db.all_running_states()
        for st in states:
            if st["next_fire_at"] > now:
                continue
            await self._post_one(st)

    async def _post_one(self, st) -> None:
        db = get_db()
        ch_id = st["channel_id"]
        ch = await db.get_channel(ch_id)
        if not ch:
            await db.set_posting_state(ch_id, is_running=0)
            return
        helper = await db.get_helper(ch["helper_id"])
        if not helper or not helper["is_alive"]:
            await db.set_posting_state(ch_id, is_running=0)
            log.info("[ch %s] постинг остановлен — помощник %s мёртв",
                     ch_id, ch["helper_id"])
            return
        manager = get_manager()
        bot = manager.get_helper_bot(helper["id"])
        if bot is None:
            log.warning("[ch %s] нет активного Bot у помощника %s",
                        ch_id, helper["id"])
            return

        try:
            task_ids = json.loads(st["task_ids"] or "[]")
        except Exception:
            task_ids = []
        if not task_ids:
            await db.set_posting_state(ch_id, is_running=0)
            return

        tasks_posts: list[list] = []
        for tid in task_ids:
            tasks_posts.append(await db.list_posts(tid))

        t_idx = st["cur_task_idx"]
        p_idx = st["cur_post_idx"]

        if t_idx >= len(tasks_posts):
            t_idx, p_idx = 0, 0
        safety = 0
        while tasks_posts and not tasks_posts[t_idx] and safety < len(tasks_posts) + 1:
            t_idx = (t_idx + 1) % len(tasks_posts)
            p_idx = 0
            safety += 1
        if not tasks_posts or not tasks_posts[t_idx]:
            await db.set_posting_state(ch_id, is_running=0)
            log.info("[ch %s] постинг остановлен — нет постов", ch_id)
            return
        if p_idx >= len(tasks_posts[t_idx]):
            p_idx = 0

        post = tasks_posts[t_idx][p_idx]

        try:
            msg_id = await send_post(bot, ch["chat_id"], post)
            if msg_id and post["delete_after"] > 0:
                await db.add_pending_delete(
                    helper["id"], ch["chat_id"], msg_id,
                    int(time.time()) + post["delete_after"],
                )
            log.info("[ch %s/helper %s] опубликован пост %s",
                     ch_id, helper["id"], post["id"])
        except TelegramUnauthorizedError as e:
            # Помощник заморожен/удалён — помечаем dead, уведомление уйдёт
            await get_manager().report_helper_error(helper["id"], e)
            return
        except Exception as e:
            msg = str(e).lower()
            if "unauthorized" in msg:
                await get_manager().report_helper_error(helper["id"], e)
                return
            log.warning("[ch %s] ошибка публикации: %s", ch_id, e)

        next_p = p_idx + 1
        next_t = t_idx
        if next_p >= len(tasks_posts[t_idx]):
            next_p = 0
            next_t = (t_idx + 1) % len(tasks_posts)

        delay = max(1, post["next_delay"])
        await db.set_posting_state(
            ch_id,
            cur_task_idx=next_t,
            cur_post_idx=next_p,
            next_fire_at=int(time.time()) + delay,
        )

    async def _process_deletes(self) -> None:
        db = get_db()
        manager = get_manager()
        now = int(time.time())
        due = await db.due_pending_deletes(now)
        for pd in due:
            bot = manager.get_helper_bot(pd["helper_id"])
            if bot is None:
                await db.remove_pending_delete(pd["id"])
                continue
            try:
                await bot.delete_message(pd["chat_id"], pd["message_id"])
            except TelegramUnauthorizedError as e:
                await manager.report_helper_error(pd["helper_id"], e)
            except Exception as e:
                log.warning("автоудаление %s/%s: %s",
                            pd["chat_id"], pd["message_id"], e)
            await db.remove_pending_delete(pd["id"])


_engine: PosterEngine | None = None


def get_poster() -> PosterEngine:
    global _engine
    if _engine is None:
        _engine = PosterEngine()
    return _engine
