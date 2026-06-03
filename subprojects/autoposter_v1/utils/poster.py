"""Движок автопостинга: цикл публикации по кругу + автоудаление."""
from __future__ import annotations

import asyncio
import json
import logging
import time

from aiogram import Bot

from database import get_db
from utils.helpers import send_post

log = logging.getLogger("poster")


class PosterEngine:
    """Один фоновый цикл на весь автопостер.

    Каждые ~5 секунд проверяет все каналы с is_running=1:
    если пришло время (next_fire_at <= now) — публикует текущий пост,
    сдвигает указатель на следующий, считает next_fire_at.
    Порядок: все посты задачи 1, потом задачи 2, ... потом по кругу.
    """

    def __init__(self) -> None:
        self._bot: Bot | None = None
        self._task: asyncio.Task | None = None

    def start(self, bot: Bot) -> None:
        self._bot = bot
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
        """Публикует текущий пост канала и сдвигает указатель."""
        db = get_db()
        channel_id = st["channel_id"]
        ch = await db.get_channel(channel_id)
        if not ch:
            await db.set_posting_state(channel_id, is_running=0)
            return

        try:
            task_ids = json.loads(st["task_ids"] or "[]")
        except Exception:
            task_ids = []
        if not task_ids:
            await db.set_posting_state(channel_id, is_running=0)
            return

        # собираем плоскую очередь постов: [(task_idx, post_row), ...]
        tasks_posts: list[list] = []
        for tid in task_ids:
            posts = await db.list_posts(tid)
            tasks_posts.append(posts)

        t_idx = st["cur_task_idx"]
        p_idx = st["cur_post_idx"]

        # нормализуем указатель (задачи/посты могли измениться)
        if t_idx >= len(tasks_posts):
            t_idx, p_idx = 0, 0
        # пропускаем пустые задачи
        safety = 0
        while tasks_posts and not tasks_posts[t_idx] and safety < len(tasks_posts) + 1:
            t_idx = (t_idx + 1) % len(tasks_posts)
            p_idx = 0
            safety += 1
        if not tasks_posts or not tasks_posts[t_idx]:
            # вообще нет постов — стоп
            await db.set_posting_state(channel_id, is_running=0)
            log.info("[ch %s] постинг остановлен — нет постов", channel_id)
            return
        if p_idx >= len(tasks_posts[t_idx]):
            p_idx = 0

        post = tasks_posts[t_idx][p_idx]

        # публикуем
        try:
            msg_id = await send_post(self._bot, ch["chat_id"], post)
            if msg_id and post["delete_after"] > 0:
                await db.add_pending_delete(
                    ch["chat_id"], msg_id, int(time.time()) + post["delete_after"]
                )
            log.info("[ch %s] опубликован пост %s (задача idx %s)",
                     channel_id, post["id"], t_idx)
        except Exception as e:
            log.warning("[ch %s] ошибка публикации поста %s: %s",
                        channel_id, post["id"], e)

        # сдвигаем указатель на следующий пост (по кругу)
        next_p = p_idx + 1
        next_t = t_idx
        if next_p >= len(tasks_posts[t_idx]):
            next_p = 0
            next_t = (t_idx + 1) % len(tasks_posts)

        delay = max(1, post["next_delay"])
        await db.set_posting_state(
            channel_id,
            cur_task_idx=next_t,
            cur_post_idx=next_p,
            next_fire_at=int(time.time()) + delay,
        )

    async def _process_deletes(self) -> None:
        """Удаляет посты, которым пришло время автоудаления."""
        db = get_db()
        now = int(time.time())
        due = await db.due_pending_deletes(now)
        for pd in due:
            try:
                await self._bot.delete_message(pd["chat_id"], pd["message_id"])
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
