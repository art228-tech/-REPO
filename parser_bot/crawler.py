"""Оркестратор парсинга: очередь чатов, интервалы, режим перепроверки."""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from .config import Config
from .database import Database
from .userbot import ProbeResult, UserBot
from .utils import ChatRef, normalize

log = logging.getLogger(__name__)

NotifyFn = Callable[[str], Awaitable[None]]


class Crawler:
    def __init__(self, cfg: Config, db: Database, userbot: UserBot, notify: NotifyFn):
        self.cfg = cfg
        self.db = db
        self.userbot = userbot
        self.notify = notify
        self._task: Optional[asyncio.Task] = None
        self.mode: Optional[str] = None  # 'crawl' | 'recheck'

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def min_members(self) -> int:
        return await self.db.get_int_setting("min_members", self.cfg.min_members)

    async def min_msgs_per_day(self) -> int:
        return await self.db.get_int_setting(
            "min_messages_per_day", self.cfg.min_messages_per_day
        )

    # ---------- управление ----------
    async def add_seed(self, raw: str) -> bool:
        ref = normalize(raw)
        if not ref:
            return False
        return await self.db.add_chat(ref.ident, ref.link, status="queue", source="seed")

    async def start(self) -> str:
        if self.running:
            return f"Парсинг уже идёт (режим: {self.mode})."
        if not await self.userbot.is_authorized():
            return "Сначала войдите в аккаунт."
        if await self.db.pending_count() == 0:
            return "Очередь пуста. Сначала пришлите ссылку на чат."
        self.mode = "crawl"
        self._task = asyncio.create_task(self._crawl_loop())
        return "Парсинг запущен."

    async def start_recheck(self) -> str:
        if self.running:
            return f"Сейчас уже идёт процесс ({self.mode}). Сначала остановите его."
        if not await self.userbot.is_authorized():
            return "Сначала войдите в аккаунт."
        idents = await self.db.idents_by_status("unrestricted")
        if not idents:
            return "База без ограничений пуста — перепроверять нечего."
        self.mode = "recheck"
        self._task = asyncio.create_task(self._recheck_loop(idents))
        return f"Перепроверка запущена: {len(idents)} чат(ов)."

    async def stop(self) -> str:
        if not self.running:
            return "Парсинг не запущен."
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        self.mode = None
        return "Парсинг остановлен."

    # ---------- циклы ----------
    async def _crawl_loop(self) -> None:
        try:
            while True:
                row = await self.db.next_pending()
                if row is None:
                    await self.notify(
                        "✅ Очередь пуста — проверять больше нечего. Парсинг остановлен."
                    )
                    break
                ref = normalize(row["link"]) or normalize(row["ident"])
                if ref is None:
                    await self.db.update_status(row["ident"], "error",
                                                reason="не удалось разобрать ссылку")
                    continue
                try:
                    result = await self.userbot.probe(ref)
                except Exception as e:  # noqa: BLE001
                    log.exception("probe failed")
                    await self.db.update_status(row["ident"], "error", reason=str(e))
                    await asyncio.sleep(self.cfg.check_interval)
                    continue
                await self._apply_result(row["ident"], result, enqueue_children=True)
                await asyncio.sleep(self.cfg.check_interval)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("crawl loop crashed")
            await self.notify(f"⚠️ Парсинг упал с ошибкой: {e}")
        finally:
            self._task = None
            self.mode = None

    async def _recheck_loop(self, idents: list[str]) -> None:
        try:
            changed = 0
            for ident in idents:
                row = await self.db.get(ident)
                if row is None:
                    continue
                ref = normalize(row["link"]) or normalize(ident)
                if ref is None:
                    continue
                try:
                    result = await self.userbot.probe(ref)
                except Exception as e:  # noqa: BLE001
                    await self.db.update_status(ident, "error", reason=str(e))
                    await asyncio.sleep(self.cfg.check_interval)
                    continue
                new_status = await self._apply_result(ident, result, enqueue_children=True)
                if new_status != "unrestricted":
                    changed += 1
                await asyncio.sleep(self.cfg.check_interval)
            await self.notify(
                f"🔁 Перепроверка завершена. Изменили статус: {changed} из {len(idents)}."
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("recheck loop crashed")
            await self.notify(f"⚠️ Перепроверка упала с ошибкой: {e}")
        finally:
            self._task = None
            self.mode = None

    # ---------- применение результата ----------
    async def _apply_result(
        self, ident: str, result: ProbeResult, *, enqueue_children: bool
    ) -> str:
        if result.status == "error":
            await self.db.update_status(
                ident, "error", title=result.title, chat_id=result.chat_id,
                members=result.members, reason=result.reason,
            )
            return "error"

        if result.status == "captcha":
            await self.db.update_status(
                ident, "captcha", title=result.title, chat_id=result.chat_id,
                members=result.members, reason=result.reason,
            )
            return "captcha"

        if result.status == "not_chat":
            # в ОП могут стоять каналы/боты/юзеры — всё кроме чатов в мусор
            await self.db.update_status(
                ident, "not_chat", title=result.title, chat_id=result.chat_id,
                members=result.members, reason=result.reason,
            )
            return "not_chat"

        if result.status == "op":
            # сам чат -> ОП проверенные, его список ОП -> в очередь как op_unchecked
            await self.db.update_status(
                ident, "op_checked", title=result.title, chat_id=result.chat_id,
                members=result.members, reason=result.reason,
            )
            if enqueue_children:
                for child in result.op_refs:
                    if child.ident == ident:
                        continue
                    await self.db.add_chat(
                        child.ident, child.link, status="op_unchecked", source=ident
                    )
            return "op_checked"

        # status == 'clean' — проверяем участников и активность
        min_m = await self.min_members()
        min_msg = await self.min_msgs_per_day()
        if result.members < min_m:
            await self.db.update_status(
                ident, "small", title=result.title, chat_id=result.chat_id,
                members=result.members, msgs_per_day=result.msgs_per_day,
                reason=f"участников {result.members} < {min_m}",
            )
            return "small"
        if result.msgs_per_day < min_msg:
            await self.db.update_status(
                ident, "low_activity", title=result.title, chat_id=result.chat_id,
                members=result.members, msgs_per_day=result.msgs_per_day,
                reason=f"сообщений/сутки {result.msgs_per_day} < {min_msg}",
            )
            return "low_activity"
        await self.db.update_status(
            ident, "unrestricted", title=result.title, chat_id=result.chat_id,
            members=result.members, msgs_per_day=result.msgs_per_day,
            reason=result.reason,
        )
        return "unrestricted"
