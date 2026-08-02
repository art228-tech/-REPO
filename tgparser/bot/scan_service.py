"""Запуск обходов в фоне и сведение результатов.

Бот многопользовательский, поэтому прогоны идут параллельно и учитываются
по владельцу: у каждого свой аккаунт, свои бюджеты и свой архивный канал.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from telethon.errors import ApiIdPublishedFloodError, AuthKeyError, RPCError

from tgparser.config import Settings
from tgparser.core.archive import Archive
from tgparser.core.scanner import Scanner, ScanReport
from tgparser.core.util import humanize_seconds
from tgparser.crypto import SessionCipher, SessionCipherError
from tgparser.db.repo import AccountRepo, ChatStateRepo
from tgparser.db.settings_store import Pace, load_settings
from tgparser.ratelimit.guard import FloodGuard, build_buckets

logger = logging.getLogger(__name__)


class ScanBusyError(RuntimeError):
    pass


@dataclass(slots=True)
class ScanSlot:
    task: asyncio.Task
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    report: ScanReport | None = None
    error: str | None = None


class ScanService:
    def __init__(self, app_settings: Settings, cipher: SessionCipher, db: Any) -> None:
        self._app_settings = app_settings
        self._cipher = cipher
        self._db = db
        self._slots: dict[int, ScanSlot] = {}

    def is_running(self, owner_id: int) -> bool:
        slot = self._slots.get(owner_id)
        return slot is not None and not slot.task.done()

    @property
    def running_count(self) -> int:
        return sum(1 for slot in self._slots.values() if not slot.task.done())

    def last_report(self, owner_id: int) -> ScanReport | None:
        slot = self._slots.get(owner_id)
        return slot.report if slot else None

    def last_error(self, owner_id: int) -> str | None:
        slot = self._slots.get(owner_id)
        return slot.error if slot else None

    async def start(
        self, owner_id: int, resume: bool, on_progress: Any, on_status: Any = None
    ) -> None:
        if self.is_running(owner_id):
            raise ScanBusyError("Обход уже идёт")
        # create_task не выполняет корутину синхронно, поэтому слот успевает
        # зарегистрироваться раньше, чем _run дойдёт до первого await.
        task = asyncio.create_task(self._run(owner_id, resume, on_progress, on_status))
        self._slots[owner_id] = ScanSlot(task=task)

    async def stop(self, owner_id: int) -> bool:
        if not self.is_running(owner_id):
            return False
        task = self._slots[owner_id].task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.info("Обход %s отменён по запросу", owner_id)
        except Exception:
            logger.exception("Обход %s завершился ошибкой при остановке", owner_id)
        return True

    async def stop_all(self) -> None:
        for owner_id in list(self._slots):
            await self.stop(owner_id)

    def _note(self, owner_id: int, *, error: str | None = None, report: ScanReport | None = None):
        slot = self._slots.get(owner_id)
        if slot is None:
            return
        if error is not None:
            slot.error = error
        if report is not None:
            slot.report = report

    async def _run(
        self, owner_id: int, resume: bool, on_progress: Any, on_status: Any = None
    ) -> None:
        client = None
        guard: FloodGuard | None = None
        account_id: int | None = None
        try:
            async with self._db.session() as session:
                account = await AccountRepo(session, owner_id).first_active()
                if account is None:
                    await self._fail(owner_id, on_progress, "Аккаунт не подключён.")
                    return
                if AccountRepo.is_blocked(account):
                    await self._fail(
                        owner_id,
                        on_progress,
                        f"Аккаунт выведен из работы до "
                        f"{account.blocked_until:%d.%m %H:%M} — {account.block_reason}.",
                    )
                    return
                scan_settings = await load_settings(session, owner_id)
                if not resume:
                    reset = await ChatStateRepo(session).reset(account.id)
                    if reset:
                        await on_progress(f"Чекпоинты сброшены ({reset} чатов).")
                account_id = account.id
                archive_channel_id = account.archive_channel_id
                pace = Pace(scan_settings, account.calls_done, account.flood_events)

            from tgparser.userbot.client import client_for_account

            async with self._db.session() as session:
                account = await AccountRepo(session, owner_id).get(account_id)
                client = await client_for_account(self._app_settings, account, self._cipher)

            if not await client.is_user_authorized():
                # Убираем из работы, иначе каждый запуск будет упираться в ту
                # же мёртвую сессию и подключить новый аккаунт не выйдет.
                async with self._db.session() as session:
                    repo = AccountRepo(session, owner_id)
                    account = await repo.get(account_id)
                    if account is not None:
                        await repo.deactivate(account, "сессия отозвана")
                await self._fail(
                    owner_id,
                    on_progress,
                    "Сессия недействительна: аккаунт вышел или сессию завершили "
                    "в «Устройствах». Аккаунт отключён — подключите заново, "
                    "можно другой номер.",
                )
                return

            me = await client.get_me()
            guard = FloodGuard(
                buckets=build_buckets(pace.roster, pace.history, pace.write),
                min_delay=scan_settings.min_delay_sec,
                max_delay=scan_settings.max_delay_sec,
                max_flood_wait=scan_settings.max_flood_wait_sec,
            )
            async def remember_archive(channel_id: int) -> None:
                async with self._db.session() as session:
                    account = await AccountRepo(session, owner_id).get(account_id)
                    if account is not None:
                        account.archive_channel_id = channel_id

            archive = Archive(client, guard, archive_channel_id, remember_archive)

            if pace.reason:
                await on_progress(pace.reason.capitalize() + ".")

            scanner = Scanner(
                client=client,
                guard=guard,
                settings=scan_settings,
                db=self._db,
                account_id=account_id,
                owner_id=owner_id,
                self_id=getattr(me, "id", 0),
                archive=archive,
                on_progress=on_progress,
                on_status=on_status,
            )
            report = await scanner.run()
            self._note(owner_id, report=report)

            async with self._db.session() as session:
                repo = AccountRepo(session, owner_id)
                account = await repo.get(account_id)
                if account is not None and archive.channel_id:
                    account.archive_channel_id = archive.channel_id
                if report.flagged and account is not None:
                    await repo.block(
                        account,
                        scan_settings.peer_flood_cooldown_hours,
                        "PeerFlood: Telegram счёл активность спам-риском",
                    )

            summary = format_report(report, guard)
            await on_progress(summary)
            await archive.post(summary)

        except asyncio.CancelledError:
            self._note(owner_id, error="Обход остановлен вручную. Прогресс сохранён.")
            await on_progress("Обход остановлен вручную. Прогресс сохранён.")
            raise
        except SessionCipherError as exc:
            await self._fail(owner_id, on_progress, str(exc))
        except ApiIdPublishedFloodError:
            logger.warning("api_id аккаунта %s ограничен как засвеченный", owner_id)
            await self._fail(
                owner_id,
                on_progress,
                "Telegram ограничил api_id как засвеченный в открытом доступе "
                "(API_ID_PUBLISHED_FLOOD). Подключите аккаунт заново со своим "
                "ключом с my.telegram.org.",
            )
        except (AuthKeyError, RPCError) as exc:
            logger.exception("Обход %s упал", owner_id)
            await self._fail(owner_id, on_progress, f"Ошибка Telegram: {exc}")
        except Exception as exc:
            logger.exception("Обход %s упал", owner_id)
            await self._fail(owner_id, on_progress, f"Неожиданная ошибка: {exc}")
        finally:
            # Статистика темпа копится и у прерванного прогона: иначе разгон
            # не снимется никогда, ведь полный обход идёт сутками и до конца
            # может не дойти ни разу.
            await self._record_pace(owner_id, account_id, guard)
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    logger.debug("Не удалось отключить клиент", exc_info=True)

    async def _record_pace(
        self, owner_id: int, account_id: int | None, guard: FloodGuard | None
    ) -> None:
        if account_id is None or guard is None or not guard.stats.total_calls:
            return
        try:
            async with self._db.session() as session:
                account = await AccountRepo(session, owner_id).get(account_id)
                if account is None:
                    return
                account.calls_done += guard.stats.total_calls
                account.flood_events += guard.stats.flood_events
                logger.info(
                    "Аккаунт %s: запросов всего %s, FloodWait всего %s",
                    owner_id,
                    account.calls_done,
                    account.flood_events,
                )
        except Exception:
            logger.exception("Не удалось сохранить статистику темпа")

    async def _fail(self, owner_id: int, on_progress: Any, text: str) -> None:
        self._note(owner_id, error=text)
        await on_progress(text)


def format_report(report: ScanReport, guard: FloodGuard | None = None) -> str:
    lines = ["<b>Обход завершён</b>" if not report.aborted else "<b>Обход прерван</b>"]
    if report.abort_reason:
        lines.append(report.abort_reason)

    duration = ""
    if report.finished_at is not None:
        duration = humanize_seconds((report.finished_at - report.started_at).total_seconds())

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
