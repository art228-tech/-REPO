"""Прогон настоящих апдейтов через диспетчер с подменённой сессией Telegram."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import (
    Chat,
    Message,
    Update,
)

from tests.test_auth import FakeClient
from tgparser.bot.app import build_dispatcher
from tgparser.bot.context import BotContext
from tgparser.bot.scan_service import ScanService
from tgparser.config import Settings
from tgparser.crypto import SessionCipher, generate_key
from tgparser.userbot import auth as auth_module
from tgparser.userbot.auth import AuthManager

OWNER = 111
STRANGER = 222
CHAT_ID = 111


class RecordingSession(BaseSession):
    """Ничего не отправляет наружу, только записывает вызовы."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self._message_id = 1000

    def texts(self) -> list[str]:
        found = []
        for call in self.calls:
            text = getattr(call, "text", None)
            if text:
                found.append(text)
        return found

    def last_of(self, method_type: type) -> Any:
        for call in reversed(self.calls):
            if isinstance(call, method_type):
                return call
        return None

    def has(self, method_type: type) -> bool:
        return any(isinstance(call, method_type) for call in self.calls)

    async def close(self) -> None:
        return None

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes, None]:
        yield b""

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, EditMessageText, EditMessageReplyMarkup)):
            self._message_id += 1
            # Настоящий Bot.answer() отдаёт объект, привязанный к боту:
            # без привязки обработчик не сможет вызвать edit_text у ответа.
            return make_message(
                self._message_id, getattr(method, "text", "") or "", from_bot=True
            ).as_(bot)
        if isinstance(method, (AnswerCallbackQuery, DeleteMessage)):
            return True
        return True


def make_message(message_id: int, text: str, from_bot: bool = False) -> Message:
    return Message.model_validate(
        {
            "message_id": message_id,
            "date": datetime.now(UTC),
            "chat": Chat(id=CHAT_ID, type="private"),
            "from": {
                "id": 9 if from_bot else OWNER,
                "is_bot": from_bot,
                "first_name": "Бот" if from_bot else "Владелец",
            },
            "text": text,
        }
    )


def message_update(text: str, user_id: int = OWNER, update_id: int = 1) -> Update:
    return Update.model_validate(
        {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "date": datetime.now(UTC),
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": user_id, "is_bot": False, "first_name": "Кто-то"},
                "text": text,
            },
        }
    )


def callback_update(data: str, user_id: int = OWNER, update_id: int = 1) -> Update:
    return Update.model_validate(
        {
            "update_id": update_id,
            "callback_query": {
                "id": f"cb-{update_id}",
                "from": {"id": user_id, "is_bot": False, "first_name": "Кто-то"},
                "chat_instance": "instance",
                "data": data,
                "message": {
                    "message_id": 500,
                    "date": datetime.now(UTC),
                    "chat": {"id": user_id, "type": "private"},
                    "from": {"id": 9, "is_bot": True, "first_name": "Бот"},
                    "text": "предыдущее",
                },
            },
        }
    )


@pytest.fixture
def app_settings(tmp_path) -> Settings:
    return Settings(
        BOT_TOKEN="123456:AAFAKEfaketokenfaketokenfaketoken12",
        API_ID=12345,
        API_HASH="hash",
        ADMIN_ID=OWNER,
        ACCESS_MODE="allowlist",
        ALLOWED_USER_IDS=[OWNER],
        SESSION_ENCRYPTION_KEY=generate_key(),
        DB_PATH=tmp_path / "db.sqlite3",
        EXPORT_DIR=tmp_path / "exports",
    )


@pytest.fixture
def session() -> RecordingSession:
    return RecordingSession()


@pytest.fixture
def bot(app_settings, session) -> Bot:
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    return Bot(
        token=app_settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


@pytest.fixture
def userbot_client(monkeypatch) -> FakeClient:
    client = FakeClient()
    monkeypatch.setattr(auth_module, "new_client", lambda *a, **kw: client)
    return client


@pytest.fixture
def dispatcher(app_settings, db, userbot_client):
    cipher = SessionCipher(app_settings.session_encryption_key)
    ctx = BotContext(
        app_settings=app_settings,
        db=db,
        cipher=cipher,
        auth=AuthManager(app_settings, cipher, db),
        scan=ScanService(app_settings, cipher, db),
    )
    dispatcher = build_dispatcher(ctx)
    yield dispatcher
    # Роутеры объявлены на уровне модуля и в бою подключаются один раз.
    # Тестам нужен свой диспетчер на каждый случай, поэтому отцепляем.
    for router in dispatcher.sub_routers:
        router._parent_router = None
    dispatcher.sub_routers.clear()


class TestAccessControl:
    async def test_owner_gets_menu(self, dispatcher, bot, session):
        await dispatcher.feed_update(bot, message_update("/start"))
        assert session.has(SendMessage)
        assert "Парсер тематических чатов" in " ".join(session.texts())

    async def test_stranger_is_ignored(self, dispatcher, bot, session):
        await dispatcher.feed_update(bot, message_update("/start", user_id=STRANGER))
        assert session.calls == []

    async def test_stranger_callback_is_ignored(self, dispatcher, bot, session):
        await dispatcher.feed_update(bot, callback_update("scan:start", user_id=STRANGER))
        assert session.calls == []


class TestMenu:
    async def test_offers_connect_when_no_account(self, dispatcher, bot, session):
        await dispatcher.feed_update(bot, message_update("/start"))
        markup = session.last_of(SendMessage).reply_markup
        labels = [b.text for row in markup.inline_keyboard for b in row]
        assert labels == ["Подключить аккаунт"]

    async def test_unknown_command_gets_hint(self, dispatcher, bot, session):
        await dispatcher.feed_update(bot, message_update("что-то непонятное"))
        assert "/menu" in " ".join(session.texts())


class TestLoginFlow:
    async def test_full_login_by_keypad(self, dispatcher, bot, session, db):
        from tgparser.db.repo import AccountRepo

        await dispatcher.feed_update(bot, callback_update("auth:start", update_id=1))
        assert "номер" in " ".join(session.texts()).lower()

        await dispatcher.feed_update(bot, message_update("+79991234567", update_id=2))
        # Сначала бот спрашивает, откуда взять ключи приложения.
        choice = session.last_of(SendMessage).reply_markup
        options = [
            b.callback_data for row in choice.inline_keyboard for b in row if b.callback_data
        ]
        assert "keys:auto" in options
        assert "keys:manual" in options
        assert "keys:shared" in options

        await dispatcher.feed_update(bot, callback_update("keys:shared", update_id=3))
        keypad = session.last_of(SendMessage).reply_markup
        digits = [
            b.callback_data
            for row in keypad.inline_keyboard
            for b in row
            if b.callback_data and b.callback_data.startswith("code:digit:")
        ]
        assert len(digits) == 10

        for index, digit in enumerate("12345", start=4):
            await dispatcher.feed_update(
                bot, callback_update(f"code:digit:{digit}", update_id=index)
            )
        await dispatcher.feed_update(bot, callback_update("code:submit", update_id=20))

        async with db.session() as db_session:
            account = await AccountRepo(db_session, OWNER).first_active()
        assert account is not None
        assert account.phone == "+79991234567"
        # Общие ключи не копируются на аккаунт: он продолжает следовать конфигу.
        assert account.api_id is None

    async def test_manual_keys_are_saved_with_the_account(self, dispatcher, bot, db):
        from tgparser.db.repo import AccountRepo

        await dispatcher.feed_update(bot, callback_update("auth:start", update_id=1))
        await dispatcher.feed_update(bot, message_update("+79991234567", update_id=2))
        await dispatcher.feed_update(bot, callback_update("keys:manual", update_id=3))
        await dispatcher.feed_update(
            bot,
            message_update(
                "27482913 a1b2c3d4e5f60718293a4b5c6d7e8f90", update_id=4
            ),
        )
        for index, digit in enumerate("12345", start=5):
            await dispatcher.feed_update(
                bot, callback_update(f"code:digit:{digit}", update_id=index)
            )
        await dispatcher.feed_update(bot, callback_update("code:submit", update_id=20))

        async with db.session() as db_session:
            account = await AccountRepo(db_session, OWNER).first_active()
        assert account is not None
        assert account.api_id == 27482913
        # api_hash — секрет, поэтому в базе лежит зашифрованным.
        assert b"a1b2c3d4" not in (account.api_hash_enc or b"")

    async def test_malformed_manual_keys_are_rejected(self, dispatcher, bot, session, db):
        from tgparser.db.repo import AccountRepo

        await dispatcher.feed_update(bot, callback_update("auth:start", update_id=1))
        await dispatcher.feed_update(bot, message_update("+79991234567", update_id=2))
        await dispatcher.feed_update(bot, callback_update("keys:manual", update_id=3))
        await dispatcher.feed_update(bot, message_update("абракадабра", update_id=4))

        assert "Не разобрал" in " ".join(session.texts())
        async with db.session() as db_session:
            assert await AccountRepo(db_session, OWNER).first_active() is None

    async def test_code_never_travels_as_a_message(self, dispatcher, bot, session):
        """Код набирается кнопками: бот не должен ждать его сообщением."""
        await dispatcher.feed_update(bot, callback_update("auth:start", update_id=1))
        await dispatcher.feed_update(bot, message_update("+79991234567", update_id=2))
        await dispatcher.feed_update(bot, callback_update("keys:shared", update_id=3))
        session.calls.clear()

        # Пользователь всё-таки прислал код текстом — он попадает в fallback,
        # а не в обработчик входа.
        await dispatcher.feed_update(bot, message_update("12345", update_id=4))
        assert "/menu" in " ".join(session.texts())

    async def test_bad_phone_is_rejected(self, dispatcher, bot, session):
        await dispatcher.feed_update(bot, callback_update("auth:start", update_id=1))
        await dispatcher.feed_update(bot, message_update("не номер", update_id=2))
        assert "формате" in " ".join(session.texts())

    async def test_keypad_updates_on_digit(self, dispatcher, bot, session):
        await dispatcher.feed_update(bot, callback_update("auth:start", update_id=1))
        await dispatcher.feed_update(bot, message_update("+79991234567", update_id=2))
        await dispatcher.feed_update(bot, callback_update("keys:shared", update_id=3))
        await dispatcher.feed_update(bot, callback_update("code:digit:7", update_id=4))

        edit = session.last_of(EditMessageReplyMarkup)
        assert edit is not None
        header = edit.reply_markup.inline_keyboard[0][0].text
        assert "7" in header

    async def test_cancel_clears_session(self, dispatcher, bot, session):
        await dispatcher.feed_update(bot, callback_update("auth:start", update_id=1))
        await dispatcher.feed_update(bot, message_update("+79991234567", update_id=2))
        await dispatcher.feed_update(bot, callback_update("keys:shared", update_id=3))
        await dispatcher.feed_update(bot, callback_update("code:cancel", update_id=4))
        assert "отменён" in " ".join(session.texts()).lower()


class TestSettings:
    async def test_toggle_persists(self, dispatcher, bot, db):
        from tgparser.db.settings_store import load_settings

        await dispatcher.feed_update(
            bot, callback_update("settings:toggle:collect_roster", update_id=1)
        )
        async with db.session() as db_session:
            assert (await load_settings(db_session, OWNER)).collect_roster is True

    async def test_roster_toggle_shows_warning(self, dispatcher, bot, session):
        await dispatcher.feed_update(
            bot, callback_update("settings:toggle:collect_roster", update_id=1)
        )
        assert "PeerFlood" in " ".join(session.texts())

    async def test_depth_change(self, dispatcher, bot, db):
        from tgparser.db.settings_store import load_settings

        await dispatcher.feed_update(bot, callback_update("settings:depth:90", update_id=1))
        async with db.session() as db_session:
            assert (await load_settings(db_session, OWNER)).history_depth_days == 90

    async def test_unknown_toggle_is_rejected(self, dispatcher, bot, session):
        await dispatcher.feed_update(
            bot, callback_update("settings:toggle:drop_database", update_id=1)
        )
        answer = session.last_of(AnswerCallbackQuery)
        assert answer.show_alert is True


class TestManualEntry:
    async def test_adds_tags_in_bulk(self, dispatcher, bot, session, db):
        from tgparser.db.repo import LeadRepo

        await dispatcher.feed_update(bot, callback_update("db:add", update_id=1))
        await dispatcher.feed_update(
            bot, message_update("@first_one, second_one\nt.me/third_one", update_id=2)
        )

        async with db.session() as db_session:
            assert await LeadRepo(db_session, OWNER).count() == 3
        assert "Добавлено" in " ".join(session.texts())

    async def test_rejects_garbage(self, dispatcher, bot, session, db):
        from tgparser.db.repo import LeadRepo

        await dispatcher.feed_update(bot, callback_update("db:add", update_id=1))
        await dispatcher.feed_update(bot, message_update("!!! 123 ???", update_id=2))

        async with db.session() as db_session:
            assert await LeadRepo(db_session, OWNER).count() == 0
        assert "корректного тега" in " ".join(session.texts())


class TestScanGuards:
    async def test_refuses_without_account(self, dispatcher, bot, session):
        await dispatcher.feed_update(bot, callback_update("scan:start", update_id=1))
        answer = session.last_of(AnswerCallbackQuery)
        assert "подключите аккаунт" in answer.text.lower()

    async def test_refuses_when_all_sources_disabled(self, dispatcher, bot, session, db):
        from tgparser.db.repo import AccountRepo
        from tgparser.db.settings_store import ScanSettings, save_settings

        async with db.session() as db_session:
            await AccountRepo(db_session, OWNER).upsert_session(
                "+79990000000", b"enc", 1, "ivanov"
            )
            await save_settings(
                db_session,
                OWNER,
                ScanSettings(
                    collect_history=False, collect_comments=False, collect_roster=False
                ),
            )

        await dispatcher.feed_update(bot, callback_update("scan:start", update_id=1))
        answer = session.last_of(AnswerCallbackQuery)
        assert "источники" in answer.text.lower()

    async def test_refuses_while_account_is_blocked(self, dispatcher, bot, session, db):
        from tgparser.db.repo import AccountRepo

        async with db.session() as db_session:
            repo = AccountRepo(db_session, OWNER)
            account = await repo.upsert_session("+79990000000", b"enc", 1, "ivanov")
            await repo.block(account, 24, "PeerFlood")

        await dispatcher.feed_update(bot, callback_update("scan:start", update_id=1))
        answer = session.last_of(AnswerCallbackQuery)
        assert "PeerFlood" in answer.text


class TestAutoKeysFlow:
    """Путь «получить ключи автоматически» целиком, как его видит человек."""

    @pytest.fixture
    def portal(self, monkeypatch):
        from tests.test_auth import FakePortal

        instance = FakePortal()
        monkeypatch.setattr(auth_module, "PortalClient", lambda *a, **kw: instance)
        return instance

    async def _reach_portal_stage(self, dispatcher, bot):
        await dispatcher.feed_update(bot, callback_update("auth:start", update_id=1))
        await dispatcher.feed_update(bot, message_update("+79991234567", update_id=2))
        await dispatcher.feed_update(bot, callback_update("keys:auto", update_id=3))

    async def test_portal_stage_asks_for_text_not_keypad(
        self, dispatcher, bot, session, portal
    ):
        """Код портала буквенно-цифровой — цифровой пад тут показывать нельзя."""
        await self._reach_portal_stage(dispatcher, bot)

        last = session.last_of(EditMessageText)
        buttons = [
            b.callback_data
            for row in (last.reply_markup.inline_keyboard if last.reply_markup else [])
            for b in row
            if b.callback_data
        ]
        assert not any(b.startswith("code:digit:") for b in buttons)
        assert "обычным сообщением" in last.text

    async def test_alphanumeric_code_is_accepted_as_a_message(
        self, dispatcher, bot, portal
    ):
        await self._reach_portal_stage(dispatcher, bot)
        await dispatcher.feed_update(
            bot, message_update("3QvmDbabncs", update_id=4)
        )
        assert portal.submitted_code == "3QvmDbabncs"

    async def test_keypad_appears_only_for_the_telegram_code(
        self, dispatcher, bot, session, portal
    ):
        await self._reach_portal_stage(dispatcher, bot)
        await dispatcher.feed_update(bot, message_update("3QvmDbabncs", update_id=4))

        last = session.last_of(EditMessageText)
        digits = [
            b.callback_data
            for row in last.reply_markup.inline_keyboard
            for b in row
            if b.callback_data and b.callback_data.startswith("code:digit:")
        ]
        assert len(digits) == 10
        assert "кнопками" in last.text

    async def test_full_auto_flow_saves_own_keys(self, dispatcher, bot, db, portal):
        from tgparser.db.repo import AccountRepo

        await self._reach_portal_stage(dispatcher, bot)
        await dispatcher.feed_update(bot, message_update("3QvmDbabncs", update_id=4))
        for index, digit in enumerate("12345", start=5):
            await dispatcher.feed_update(
                bot, callback_update(f"code:digit:{digit}", update_id=index)
            )
        await dispatcher.feed_update(bot, callback_update("code:submit", update_id=20))

        async with db.session() as db_session:
            account = await AccountRepo(db_session, OWNER).first_active()
        assert account is not None
        assert account.api_id == 27482913

    async def test_bad_code_is_reported_and_retryable(
        self, dispatcher, bot, session, portal
    ):
        await self._reach_portal_stage(dispatcher, bot)
        await dispatcher.feed_update(bot, message_update("не код", update_id=4))
        assert "Не похоже на код" in " ".join(session.texts())
        assert portal.submitted_code is None

        # Состояние сохранилось: правильный код принимается следующим сообщением.
        await dispatcher.feed_update(bot, message_update("3QvmDbabncs", update_id=5))
        assert portal.submitted_code == "3QvmDbabncs"

    async def test_portal_refusal_offers_manual_entry(
        self, dispatcher, bot, session, portal
    ):
        from tgparser.userbot.appkeys import PortalError

        portal.request_error = PortalError("Портал отказал, вводите руками.")
        await self._reach_portal_stage(dispatcher, bot)

        last = session.last_of(EditMessageText)
        options = [
            b.callback_data
            for row in last.reply_markup.inline_keyboard
            for b in row
            if b.callback_data
        ]
        assert "keys:manual" in options


class TestOpenAccess:
    """Открытый режим: пускаем всех, но данные у каждого свои."""

    @pytest.fixture
    def open_dispatcher(self, app_settings, db, userbot_client):
        app_settings.access_mode = "open"
        app_settings.allowed_user_ids = []
        cipher = SessionCipher(app_settings.session_encryption_key)
        ctx = BotContext(
            app_settings=app_settings,
            db=db,
            cipher=cipher,
            auth=AuthManager(app_settings, cipher, db),
            scan=ScanService(app_settings, cipher, db),
        )
        dispatcher = build_dispatcher(ctx)
        yield dispatcher
        for router in dispatcher.sub_routers:
            router._parent_router = None
        dispatcher.sub_routers.clear()

    async def test_stranger_gets_a_menu(self, open_dispatcher, bot, session):
        await open_dispatcher.feed_update(
            bot, message_update("/start", user_id=STRANGER)
        )
        assert "Парсер тематических чатов" in " ".join(session.texts())

    async def test_two_users_keep_separate_databases(self, open_dispatcher, bot, db):
        from tgparser.db.repo import LeadRepo

        for update_id, user_id, tag in (
            (1, OWNER, "@alpha_one"),
            (3, STRANGER, "@beta_two"),
        ):
            await open_dispatcher.feed_update(
                bot, callback_update("db:add", user_id=user_id, update_id=update_id)
            )
            await open_dispatcher.feed_update(
                bot, message_update(tag, user_id=user_id, update_id=update_id + 1)
            )

        async with db.session() as db_session:
            owner_leads = await LeadRepo(db_session, OWNER).count()
            stranger_leads = await LeadRepo(db_session, STRANGER).count()
        assert owner_leads == 1
        assert stranger_leads == 1

    async def test_settings_of_one_user_do_not_affect_another(
        self, open_dispatcher, bot, db
    ):
        from tgparser.db.settings_store import load_settings

        await open_dispatcher.feed_update(
            bot, callback_update("settings:depth:7", user_id=OWNER, update_id=1)
        )
        async with db.session() as db_session:
            assert (await load_settings(db_session, OWNER)).history_depth_days == 7
            assert (await load_settings(db_session, STRANGER)).history_depth_days == 30

    async def test_admin_command_only_for_admin(self, open_dispatcher, bot, session):
        await open_dispatcher.feed_update(
            bot, message_update("/admin", user_id=STRANGER, update_id=1)
        )
        assert "Сводка по боту" not in " ".join(session.texts())

        session.calls.clear()
        await open_dispatcher.feed_update(
            bot, message_update("/admin", user_id=OWNER, update_id=2)
        )
        assert "Сводка по боту" in " ".join(session.texts())


class TestExport:
    async def test_empty_database_reports_nothing_to_export(self, dispatcher, bot, session):
        await dispatcher.feed_update(bot, callback_update("export:fmt:csv", update_id=1))
        assert "пустая" in " ".join(session.texts())

    async def test_sends_document_when_there_is_data(self, dispatcher, bot, session, db):
        from aiogram.methods import SendDocument

        from tgparser.db.repo import CollectedUser, LeadRepo

        async with db.session() as db_session:
            await LeadRepo(db_session, OWNER).add(
                CollectedUser(tg_user_id=1, username="ivanov")
            )

        await dispatcher.feed_update(bot, callback_update("export:fmt:xlsx", update_id=1))
        assert session.has(SendDocument)
