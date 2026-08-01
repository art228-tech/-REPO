"""Запуск обхода в фоне и сведение результатов."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from telethon.errors import AuthKeyError, RPCError

from tgparser.config import Settings
from tgparser.core.archive import Archive
from tgparser.core.scanner import Scanner, ScanReport
from tgparser.core.util import humanize_seconds
from tgparser.crypto import SessionCipher, SessionCipherError
from tgparser.db.repo import AccountRepo, ChatStateRepo
from tgparser.db.settings_store import load_settings, save_settings
from tgparser.ratelimit.guard import FloodGuard, build_buckets

logger = logging.getLogger(__name__)


class ScanBusyError(RuntimeError):
    pass


class ScanService:
    def __init__(self, app_settings: Settings, cipher: SessionCipher, db: Any) -> None:
        self._app_settings = app_settings
        self._cipher = cipher
        self._db = db
        self._task: asyncio.Task | None = None
        self._cancel = asyncio.Event()
        self.last_report: ScanReport | None = None
        self.last_error: str | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, resume: bool, on_progress: Any) -> None:
        if self.is_running:
            raise ScanBusyError("Обход уже идёт")
        self._cancel.clear()
        self.last_error = None
        self._task = asyncio.create_task(self._run(resume, on_progress))

    async def stop(self) -> bool:
        if not self.is_running:
            return False
        self._cancel.set()
        task = self._task
        assert task is not None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.info("Обход отменён по запросу")
        except Exception:
            logger.exception("Обход завершился ошибкой при остановке")
        return True

    async def _run(self, resume: bool, on_progress: Any) -> None:
        client = None
        try:
            async with self._db.session() as session:
                account = await AccountRepo(session).first_active()
                if account is None:
                    self.last_error = "Аккаунт не подключён."
                    await on_progress(self.last_error)
                    return
                if AccountRepo.is_blocked(account):
                    self.last_error = (
                        f"Аккаунт выведен из работы до "
                        f"{account.blocked_until:%d.%m %H:%M} — {account.block_reason}."
                    )
                    await on_progress(self.last_error)
                    return
                scan_settings = await load_settings(session)
                if not resume:
                    reset = await ChatStateRepo(session).reset(account.id)
                    if reset:
                        await on_progress(f"Чекпоинты сброшены ({reset} чатов).")
                account_id = account.id
                archive_channel_id = account.archive_channel_id

            from tgparser.userbot.client import client_for_account

            async with self._db.session() as session:
                account = await AccountRepo(session).get(account_id)
                client = await client_for_account(self._app_settings, account, self._cipher)

            if not await client.is_user_authorized():
                self.last_error = (
                    "Сессия недействительна — аккаунт вышел или сессия отозвана. "
                    "Подключите аккаунт заново."
                )
                await on_progress(self.last_error)
                return

            me = await client.get_me()
            guard = FloodGuard(
                buckets=build_buckets(
                    scan_settings.effective_roster_budget(),
                    scan_settings.effective_history_budget(),
                ),
                min_delay=scan_settings.min_delay_sec,
                max_delay=scan_settings.max_delay_sec,
                max_flood_wait=scan_settings.max_flood_wait_sec,
            )
            archive = Archive(client, guard, archive_channel_id)

            if scan_settings.in_warmup:
                await on_progress(
                    "Режим разгона: бюджет запросов снижен "
                    f"до {int(scan_settings.warmup_factor * 100)}%."
                )

            scanner = Scanner(
                client=client,
                guard=guard,
                settings=scan_settings,
                db=self._db,
                account_id=account_id,
                self_id=getattr(me, "id", 0),
                archive=archive,
                on_progress=on_progress,
            )
            report = await scanner.run()
            self.last_report = report

            async with self._db.session() as session:
                account = await AccountRepo(session).get(account_id)
                if account is not None and archive.channel_id:
                    account.archive_channel_id = archive.channel_id
                if report.flagged and account is not None:
                    await AccountRepo(session).block(
                        account,
                        scan_settings.peer_flood_cooldown_hours,
                        "PeerFlood: Telegram счёл активность спам-риском",
                    )
                if not report.aborted:
                    fresh = await load_settings(session)
                    if fresh.in_warmup:
                        fresh.warmup_runs_done += 1
                        await save_settings(session, fresh)

            summary = format_report(report, guard)
            await on_progress(summary)
            await archive.post(summary)

        except asyncio.CancelledError:
            self.last_error = "Обход остановлен вручную. Прогресс сохранён."
            await on_progress(self.last_error)
            raise
        except SessionCipherError as exc:
            self.last_error = str(exc)
            await on_progress(self.last_error)
        except (AuthKeyError, RPCError) as exc:
            self.last_error = f"Ошибка Telegram: {exc}"
            logger.exception("Обход упал")
            await on_progress(self.last_error)
        except Exception as exc:
            self.last_error = f"Неожиданная ошибка: {exc}"
            logger.exception("Обход упал")
            await on_progress(self.last_error)
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    logger.debug("Не удалось отключить клиент", exc_info=True)


def format_report(report: ScanReport, guard: FloodGuard | None = None) -> str:
    lines = ["<b>Обход завершён</b>" if not report.aborted else "<b>Обход прерван</b>"]
    if report.abort_reason:
        lines.append(report.abort_reason)

    duration = ""
    if report.finished_at is not None:
        duration = humanize_seconds(
            (report.finished_at - report.started_at).total_seconds()
        )

    lines.append("")
    lines.append(f"Новых записей: <b>{report.new_leads}</b>")
    lines.append(f"Чатов обойдено: {report.chats_scanned} из {report.dialogs_total}")
    if report.chats_skipped:
        lines.append(f"Пропущено: {report.chats_skipped}")
    lines.append(f"Сообщений просмотрено: {report.scanned_messages}")
    if report.forwarded:
        lines.append(f"Карточек переслано: {report.forwarded}")
    if report.anonymized:
        lines.append(
            f"Из них без ссылки на автора: {report.anonymized} "
            "(у пользователя закрыты пересылки)"
        )
    if duration:
        lines.append(f"Время: {duration}")

    if guard is not None:
        stats = guard.stats
        lines.append("")
        lines.append(
            f"Запросов: {stats.total_calls} "
            f"(история {stats.calls.get('history', 0)}, "
            f"ростер {stats.calls.get('roster', 0)})"
        )
        if stats.flood_events:
            lines.append(
                f"FloodWait: {stats.flood_events} раз, "
                f"суммарно {humanize_seconds(stats.flood_waits)}"
            )

    problem_chats = [c for c in report.chats if c.error]
    if problem_chats:
        lines.append("")
        lines.append("С ошибками:")
        for chat in problem_chats[:10]:
            lines.append(f"• {chat.title}: {chat.error}")

    return "\n".join(lines)
