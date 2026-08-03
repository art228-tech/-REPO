from __future__ import annotations

import asyncio
import random
import time
from typing import Awaitable, Callable

from telethon.errors import (
    FloodWaitError,
    PeerFloodError,
    UserDeactivatedBanError,
    UserPrivacyRestrictedError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
    AuthKeyUnregisteredError,
    SessionRevokedError,
)
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.types import InputPhoneContact

from accounts import (
    clear_spamblock_flag,
    disconnect_all,
    get_runtime_client,
    mark_spamblock,
)
from db import db
from logger_setup import log

StatsCallback = Callable[[str], Awaitable[None]]


class MailingWorker:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._stats_callback: StatsCallback | None = None
        self._last_stats_push = 0.0
        self._account_next_free: dict[int, float] = {}
        self._sent_this_run = 0
        self._failed_this_run = 0
        self._spamblocks_this_run = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, chat_id: int, stats_callback: StatsCallback) -> None:
        if self.running:
            raise RuntimeError("Рассылка уже запущена")

        api_id, api_hash = await db.get_api_credentials()
        if not api_id or not api_hash:
            raise RuntimeError("Не заданы API_ID / API_HASH")

        accounts = await db.active_accounts()
        if not accounts:
            # On resume, try clearing spamblock flags? User must clear manually.
            raise RuntimeError("Нет активных аккаунтов (без spamblock)")

        variants1 = await db.list_variants(1)
        if not variants1:
            raise RuntimeError("Добавь хотя бы один вариант сообщения №1")

        pending = await db.count_contacts("pending")
        processing_requeued = await db.requeue_processing()
        pending = await db.count_contacts("pending")
        if pending <= 0:
            raise RuntimeError("Нет pending-контактов для рассылки")

        self._stop_event = asyncio.Event()
        self._stats_callback = stats_callback
        self._account_next_free = {}
        self._sent_this_run = 0
        self._failed_this_run = 0
        self._spamblocks_this_run = 0
        await db.set_run(
            status="running",
            chat_id=chat_id,
            started=True,
            clear_error=True,
        )
        log.info(
            "Mailing started chat=%s pending=%s requeued=%s accounts=%s",
            chat_id,
            pending,
            processing_requeued,
            len(accounts),
        )
        self._task = asyncio.create_task(self._run_loop(), name="mailing-worker")

    async def stop(self, reason: str = "stopped_by_user") -> None:
        self._stop_event.set()
        if self._task:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=15)
            except Exception:
                self._task.cancel()
                try:
                    await self._task
                except Exception:
                    pass
            self._task = None
        await db.set_run(status="stopped", stopped=True, last_error=reason)
        log.info("Mailing stopped: %s", reason)

    async def _push_stats(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_stats_push < 3:
            return
        self._last_stats_push = now
        if not self._stats_callback:
            return
        text = await self.build_stats_text()
        try:
            await self._stats_callback(text)
        except Exception:
            log.exception("Failed to push stats")

    async def build_stats_text(self) -> str:
        run = await db.get_run()
        stats = await db.contact_stats()
        accounts = await db.list_accounts()
        between, per_acc = await db.get_delays()
        lines = [
            "📊 <b>Статистика рассылки</b>",
            f"Статус: <b>{run['status']}</b>",
            "",
            f"Всего в базе: {stats['total']}",
            f"✅ Отправлено: {stats['sent']}",
            f"⏳ Ожидают: {stats['pending']}",
            f"❌ Ошибки: {stats['failed']}",
            f"🔄 Processing: {stats.get('processing', 0)}",
            "",
            f"За этот запуск: +{self._sent_this_run} sent / {self._failed_this_run} fail / {self._spamblocks_this_run} SB",
            f"Пауза msg1→msg2: {between}с",
            f"Интервал на 1 аккаунт: {per_acc}с",
            "",
            "<b>Аккаунты:</b>",
        ]
        for acc in accounts:
            mark = {
                "active": "🟢",
                "spamblock": "🔴SB",
                "error": "🟠",
                "pending_auth": "⚪",
            }.get(acc["status"], "⚪")
            err = f" — {acc['last_error'][:80]}" if acc["last_error"] else ""
            lines.append(f"{mark} #{acc['id']} {acc['phone']} [{acc['status']}]{err}")
        if run["last_error"]:
            lines += ["", f"⚠️ {run['last_error'][:300]}"]
        return "\n".join(lines)

    async def _run_loop(self) -> None:
        try:
            await self._push_stats(force=True)
            while not self._stop_event.is_set():
                accounts = await db.active_accounts()
                if not accounts:
                    await db.set_run(
                        status="stopped",
                        stopped=True,
                        last_error="Нет активных аккаунтов (все в spamblock/error)",
                    )
                    await self._push_stats(force=True)
                    log.warning("No active accounts left, stopping")
                    break

                pending = await db.count_contacts("pending")
                if pending <= 0:
                    await db.set_run(status="finished", stopped=True, last_error="")
                    await self._push_stats(force=True)
                    log.info("All pending contacts processed")
                    break

                # Pick account with earliest free slot
                now = time.monotonic()
                accounts_sorted = sorted(
                    accounts,
                    key=lambda a: self._account_next_free.get(a["id"], 0),
                )
                account = accounts_sorted[0]
                account_id = int(account["id"])
                free_at = self._account_next_free.get(account_id, 0)
                if free_at > now:
                    wait_for = min(free_at - now, 5)
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(), timeout=wait_for
                        )
                        break
                    except asyncio.TimeoutError:
                        continue

                contact = await db.claim_pending_contact(account_id)
                if not contact:
                    await asyncio.sleep(1)
                    continue

                _, per_acc = await db.get_delays()
                try:
                    await self._process_contact(account_id, contact)
                    self._account_next_free[account_id] = time.monotonic() + per_acc
                except AccountSpamblocked:
                    self._spamblocks_this_run += 1
                    await db.requeue_contact(int(contact["id"]))
                    log.warning(
                        "Spamblock on account %s, contact %s requeued",
                        account_id,
                        contact["identifier"],
                    )
                except AccountTemporarilySkipped:
                    await db.requeue_contact(int(contact["id"]))
                    log.warning(
                        "Account %s temporarily skipped, contact %s requeued",
                        account_id,
                        contact["identifier"],
                    )
                except FatalMailingError as e:
                    await db.requeue_contact(int(contact["id"]))
                    await db.set_run(
                        status="stopped",
                        stopped=True,
                        last_error=str(e),
                    )
                    await self._push_stats(force=True)
                    log.error("Fatal mailing error: %s", e)
                    break
                except Exception as e:
                    self._failed_this_run += 1
                    await db.mark_contact_failed(int(contact["id"]), str(e)[:500])
                    self._account_next_free[account_id] = time.monotonic() + per_acc
                    log.exception(
                        "Failed contact %s via account %s",
                        contact["identifier"],
                        account_id,
                    )

                await self._push_stats()

        except Exception as e:
            log.exception("Mailing loop crashed")
            await db.set_run(status="stopped", stopped=True, last_error=str(e)[:500])
            await self._push_stats(force=True)
        finally:
            self._task = None
            await self._push_stats(force=True)

    async def _process_contact(self, account_id: int, contact) -> None:
        variants1 = await db.list_variants(1)
        variants2 = await db.list_variants(2)
        if not variants1:
            raise FatalMailingError("Нет вариантов сообщения №1")

        msg1 = random.choice([v["text"] for v in variants1])
        msg2 = random.choice([v["text"] for v in variants2]) if variants2 else None
        between, _ = await db.get_delays()

        client = await get_runtime_client(account_id)
        entity = await self._resolve_entity(client, contact["identifier"])

        try:
            await self._send_with_flood_wait(client, entity, msg1)
            if msg2:
                if between > 0:
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(), timeout=between
                        )
                        await db.mark_contact_sent(
                            int(contact["id"]), account_id, msg1, None
                        )
                        self._sent_this_run += 1
                        raise FatalMailingError("Остановлено пользователем после msg1")
                    except asyncio.TimeoutError:
                        pass
                await self._send_with_flood_wait(client, entity, msg2)
            await db.mark_contact_sent(
                int(contact["id"]), account_id, msg1, msg2
            )
            self._sent_this_run += 1
            log.info(
                "Sent to %s via account %s", contact["identifier"], account_id
            )
        except PeerFloodError as e:
            await mark_spamblock(account_id, f"PeerFloodError: {e}")
            raise AccountSpamblocked() from e
        except FloodWaitError as e:
            log.warning("Long FloodWait %ss on account %s", e.seconds, account_id)
            self._account_next_free[account_id] = time.monotonic() + e.seconds + 1
            if e.seconds >= 3600:
                await mark_spamblock(account_id, f"FloodWait {e.seconds}s")
                raise AccountSpamblocked() from e
            raise AccountTemporarilySkipped() from e
        except (AuthKeyUnregisteredError, SessionRevokedError, UserDeactivatedBanError) as e:
            await db.update_account(
                account_id, status="error", last_error=str(e)[:300]
            )
            raise AccountTemporarilySkipped() from e
        except (
            UserPrivacyRestrictedError,
            UsernameInvalidError,
            UsernameNotOccupiedError,
            ValueError,
        ) as e:
            await db.mark_contact_failed(int(contact["id"]), str(e)[:500])
            self._failed_this_run += 1
            log.warning("Contact permanent fail %s: %s", contact["identifier"], e)

    async def _send_with_flood_wait(self, client, entity, text: str) -> None:
        try:
            await client.send_message(entity, text)
        except FloodWaitError as e:
            if e.seconds > 300:
                raise
            log.warning("FloodWait %ss — sleeping then retry", e.seconds)
            await asyncio.sleep(e.seconds + 1)
            await client.send_message(entity, text)

    async def _resolve_entity(self, client, identifier: str):
        ident = identifier.strip()
        if ident.startswith("@"):
            return await client.get_entity(ident)
        if ident.lstrip("+").isdigit():
            phone = ident if ident.startswith("+") else f"+{ident}"
            try:
                return await client.get_entity(phone)
            except Exception:
                contact = InputPhoneContact(
                    client_id=random.randint(0, 2**31 - 1),
                    phone=phone,
                    first_name="R",
                    last_name="",
                )
                result = await client(ImportContactsRequest([contact]))
                if result.users:
                    return result.users[0]
                raise ValueError(f"Не удалось найти номер {phone}")
        if ident.isdigit():
            return await client.get_entity(int(ident))
        return await client.get_entity(ident)


class AccountSpamblocked(Exception):
    pass


class AccountTemporarilySkipped(Exception):
    pass


class FatalMailingError(Exception):
    pass


worker = MailingWorker()


async def resume_after_spamblock_check(chat_id: int, stats_callback: StatsCallback) -> str:
    """
    On continue: clear spamblock flags on user request path is separate.
    Here we re-check previously spamblocked accounts by clearing flag only if user asked,
    or just start with currently active accounts.
    """
    # Requeue stuck processing
    await db.requeue_processing()
    spamblocked = [
        a for a in await db.list_accounts() if a["status"] == "spamblock"
    ]
    notes = []
    for acc in spamblocked:
        # User said: on continue, recheck SB. We temporarily activate and let PeerFlood mark again.
        await clear_spamblock_flag(int(acc["id"]))
        notes.append(f"#{acc['id']} {acc['phone']} снят флаг SB (будет проверен при отправке)")
    await worker.start(chat_id, stats_callback)
    return "\n".join(notes) if notes else "Старт без spamblock-аккаунтов"