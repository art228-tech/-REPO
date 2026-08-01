from __future__ import annotations

import pytest
from telethon.errors import (
    ApiIdInvalidError,
    ApiIdPublishedFloodError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    SessionPasswordNeededError,
)

from tgparser.config import Settings
from tgparser.crypto import SessionCipher, generate_key
from tgparser.db.repo import AccountRepo
from tgparser.userbot import auth as auth_module
from tgparser.userbot.appkeys import (
    AppKeys,
    PortalError,
    PortalLogin,
    normalize_portal_code,
)
from tgparser.userbot.auth import (
    AuthManager,
    Outcome,
    PendingAuth,
    Stage,
    normalize_phone,
    parse_keys,
)

OWNER = 111


class FakeSession:
    def save(self) -> str:
        return "1BVtsFAKESESSION"


class FakeMe:
    id = 424242
    username = "ivanov"
    first_name = "Пётр"


class FakeClient:
    """Заглушка Telethon: сценарии входа задаются через sign_in_effects."""

    def __init__(self, sign_in_effects: list | None = None) -> None:
        self.session = FakeSession()
        self.connected = False
        self.disconnected = False
        self.sign_in_calls: list[dict] = []
        self._effects = list(sign_in_effects or [])
        self.send_code_error: Exception | None = None

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def send_code_request(self, phone: str):
        if self.send_code_error is not None:
            raise self.send_code_error

        class Sent:
            phone_code_hash = "hash-abc"

        return Sent()

    async def sign_in(self, **kwargs):
        self.sign_in_calls.append(kwargs)
        if self._effects:
            effect = self._effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
        return FakeMe()

    async def get_me(self):
        return FakeMe()


@pytest.fixture
def app_settings(tmp_path) -> Settings:
    return Settings(
        BOT_TOKEN="token",
        API_ID=12345,
        API_HASH="hash",
        SESSION_ENCRYPTION_KEY=generate_key(),
        DB_PATH=tmp_path / "db.sqlite3",
        EXPORT_DIR=tmp_path / "exports",
    )


@pytest.fixture
def manager(app_settings, db, monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(auth_module, "new_client", lambda *a, **kw: client)
    cipher = SessionCipher(app_settings.session_encryption_key)
    mgr = AuthManager(app_settings, cipher, db)
    mgr.fake_client = client
    return mgr


class TestNormalizePhone:
    @pytest.mark.parametrize(
        "raw",
        ["+7 999 123-45-67", "79991234567", "+7(999)1234567", " 7 999 123 45 67 "],
    )
    def test_accepts_common_forms(self, raw):
        assert normalize_phone(raw) == "+79991234567"

    @pytest.mark.parametrize("raw", ["", "123", "не номер", "1" * 20])
    def test_rejects_garbage(self, raw):
        assert normalize_phone(raw) is None


class TestParseKeys:
    def test_space_separated(self):
        keys = parse_keys("27482913 a1b2c3d4e5f60718293a4b5c6d7e8f90")
        assert keys.api_id == 27482913
        assert keys.api_hash == "a1b2c3d4e5f60718293a4b5c6d7e8f90"

    def test_order_does_not_matter(self):
        keys = parse_keys("a1b2c3d4e5f60718293a4b5c6d7e8f90, 27482913")
        assert keys.api_id == 27482913

    def test_newline_and_labels_tolerated(self):
        keys = parse_keys("api_id: 27482913\napi_hash: A1B2C3D4E5F60718293A4B5C6D7E8F90")
        assert keys.api_id == 27482913
        assert keys.api_hash == "a1b2c3d4e5f60718293a4b5c6d7e8f90"

    @pytest.mark.parametrize(
        "raw",
        ["", "27482913", "a1b2c3d4e5f60718293a4b5c6d7e8f90", "абракадабра", "12 short"],
    )
    def test_rejects_incomplete(self, raw):
        assert parse_keys(raw) is None


class FakePortal:
    """Заглушка my.telegram.org."""

    keys = AppKeys(api_id=27482913, api_hash="a1b2c3d4e5f60718293a4b5c6d7e8f90")

    def __init__(self) -> None:
        self.closed = False
        self.request_error: Exception | None = None
        self.login_error: Exception | None = None
        self.keys_error: Exception | None = None
        self.submitted_code: str | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True

    async def request_code(self, phone):
        if self.request_error:
            raise self.request_error
        return PortalLogin(phone=phone, random_hash="hash-portal")

    async def login(self, login, code):
        self.submitted_code = code
        if self.login_error:
            raise self.login_error

    async def obtain_keys(self):
        if self.keys_error:
            raise self.keys_error
        return self.keys


@pytest.fixture
def portal(monkeypatch) -> FakePortal:
    instance = FakePortal()
    monkeypatch.setattr(auth_module, "PortalClient", lambda *a, **kw: instance)
    return instance


PORTAL_CODE = "3QvmDbabncs"


class TestNormalizePortalCode:
    """Код портала буквенно-цифровой, а не из цифр."""

    def test_accepts_real_looking_code(self):
        assert normalize_portal_code(PORTAL_CODE) == PORTAL_CODE

    def test_case_is_preserved(self):
        assert normalize_portal_code("aBcDeF12") == "aBcDeF12"

    def test_strips_spaces_and_punctuation(self):
        assert normalize_portal_code("  3Qvm Dbabncs.  ") == PORTAL_CODE

    def test_digits_only_also_valid(self):
        assert normalize_portal_code("123456") == "123456"

    @pytest.mark.parametrize("raw", ["", "abc", "кириллица", "with space!", "a" * 50])
    def test_rejects_garbage(self, raw):
        assert normalize_portal_code(raw) is None


class TestPortalFlow:
    async def test_requests_code_and_keeps_portal_open(self, manager, portal):
        result = await manager.start_portal(OWNER, "+79991234567")
        assert result.outcome is Outcome.PORTAL_CODE_SENT
        pending = manager.get(OWNER)
        assert pending.stage is Stage.PORTAL_CODE
        assert not portal.closed

    async def test_keypad_is_inert_during_portal_stage(self, manager, portal):
        """Регресс: пад цифр не может ввести буквенный код портала."""
        await manager.start_portal(OWNER, "+79991234567")
        assert manager.push_digit(OWNER, "3") is None
        assert manager.backspace(OWNER) is None
        assert manager.get(OWNER).digits == ""

    async def test_portal_refusal_is_reported_and_cleaned_up(self, manager, portal):
        portal.request_error = PortalError("Портал отказал. my.telegram.org вручную.")
        result = await manager.start_portal(OWNER, "+79991234567")
        assert result.outcome is Outcome.PORTAL_FAILED
        assert portal.closed
        assert manager.get(OWNER) is None

    async def test_text_code_goes_to_portal_then_telegram(self, manager, portal):
        await manager.start_portal(OWNER, "+79991234567")
        result = await manager.submit_portal_code(OWNER, PORTAL_CODE)

        assert portal.submitted_code == PORTAL_CODE
        assert result.outcome is Outcome.CODE_SENT
        assert "27482913" in result.message
        pending = manager.get(OWNER)
        assert pending.stage is Stage.CODE
        assert pending.keys == FakePortal.keys
        # Портал больше не нужен и закрыт, дальше работает Telethon.
        assert portal.closed

    async def test_code_with_stray_spaces_still_works(self, manager, portal):
        await manager.start_portal(OWNER, "+79991234567")
        await manager.submit_portal_code(OWNER, " 3Qvm Dbabncs ")
        assert portal.submitted_code == PORTAL_CODE

    async def test_malformed_code_is_not_sent_to_portal(self, manager, portal):
        await manager.start_portal(OWNER, "+79991234567")
        result = await manager.submit_portal_code(OWNER, "нет")
        assert result.outcome is Outcome.INVALID_CODE
        assert portal.submitted_code is None
        # Сессия жива, можно прислать заново.
        assert manager.get(OWNER) is not None

    async def test_keypad_works_after_switching_to_telegram_stage(self, manager, portal):
        await manager.start_portal(OWNER, "+79991234567")
        await manager.submit_portal_code(OWNER, PORTAL_CODE)
        assert manager.push_digit(OWNER, "7") is not None
        assert manager.get(OWNER).digits == "7"

    async def test_second_code_signs_into_telegram(self, manager, portal, db):
        await manager.start_portal(OWNER, "+79991234567")
        await manager.submit_portal_code(OWNER, PORTAL_CODE)

        for digit in "12345":
            manager.push_digit(OWNER, digit)
        result = await manager.submit_code(OWNER)

        assert result.outcome is Outcome.SIGNED_IN
        async with db.session() as session:
            account = await AccountRepo(session, OWNER).first_active()
        assert account.api_id == 27482913
        assert account.api_hash_enc is not None

    async def test_keys_are_stored_encrypted(self, manager, portal, db, app_settings):
        await manager.start_portal(OWNER, "+79991234567")
        await manager.submit_portal_code(OWNER, PORTAL_CODE)
        for digit in "12345":
            manager.push_digit(OWNER, digit)
        await manager.submit_code(OWNER)

        async with db.session() as session:
            account = await AccountRepo(session, OWNER).first_active()
        assert FakePortal.keys.api_hash.encode() not in account.api_hash_enc
        cipher = SessionCipher(app_settings.session_encryption_key)
        assert cipher.decrypt(account.api_hash_enc) == FakePortal.keys.api_hash

    async def test_rejected_code_keeps_session(self, manager, portal):
        portal.login_error = PortalError("Портал не принял код.")
        await manager.start_portal(OWNER, "+79991234567")
        result = await manager.submit_portal_code(OWNER, PORTAL_CODE)
        assert result.outcome is Outcome.PORTAL_FAILED
        assert manager.get(OWNER) is not None

    async def test_app_creation_failure_is_reported(self, manager, portal):
        portal.keys_error = PortalError("Портал отклонил создание приложения.")
        await manager.start_portal(OWNER, "+79991234567")
        result = await manager.submit_portal_code(OWNER, PORTAL_CODE)
        assert result.outcome is Outcome.PORTAL_FAILED

    async def test_submit_without_session(self, manager):
        result = await manager.submit_portal_code(OWNER, PORTAL_CODE)
        assert result.outcome is Outcome.ERROR


class TestOwnKeys:
    async def test_own_keys_are_used_and_saved(self, manager, db, app_settings):
        keys = AppKeys(api_id=555555, api_hash="f" * 32)
        await manager.start_telegram(OWNER, "+79991234567", keys)
        for digit in "12345":
            manager.push_digit(OWNER, digit)
        result = await manager.submit_code(OWNER)

        assert result.outcome is Outcome.SIGNED_IN
        async with db.session() as session:
            account = await AccountRepo(session, OWNER).first_active()
        assert account.api_id == 555555

    async def test_shared_keys_leave_account_without_own(self, manager, db):
        await manager.start_telegram(OWNER, "+79991234567", None)
        for digit in "12345":
            manager.push_digit(OWNER, digit)
        await manager.submit_code(OWNER)

        async with db.session() as session:
            account = await AccountRepo(session, OWNER).first_active()
        assert account.api_id is None
        assert account.api_hash_enc is None

    async def test_no_keys_anywhere_is_reported(self, db, monkeypatch, tmp_path):
        from tgparser.config import Settings

        settings = Settings(
            BOT_TOKEN="token",
            API_ID=0,
            API_HASH="",
            SESSION_ENCRYPTION_KEY=generate_key(),
            DB_PATH=tmp_path / "db.sqlite3",
            EXPORT_DIR=tmp_path / "exports",
            _env_file=None,
        )
        cipher = SessionCipher(settings.session_encryption_key)
        mgr = AuthManager(settings, cipher, db)

        result = await mgr.start_telegram(OWNER, "+79991234567", None)
        assert result.outcome is Outcome.ERROR
        assert "Нет ключей приложения" in result.message


class TestPendingAuthDisplay:
    def test_masks_remaining_positions(self):
        pending = PendingAuth(phone="+7", stage=Stage.CODE, digits="12")
        assert pending.masked.startswith("1 2")
        assert "·" in pending.masked

    def test_full_code_has_no_placeholder(self):
        pending = PendingAuth(phone="+7", stage=Stage.CODE, digits="12345")
        assert "·" not in pending.masked


class TestStart:
    async def test_rejects_bad_phone(self, manager):
        result = await manager.start_telegram(OWNER, "не номер", None)
        assert result.outcome is Outcome.ERROR
        assert "формате" in result.message

    async def test_rejects_bad_proxy(self, manager):
        result = await manager.start_telegram(OWNER, "+79991234567", None, proxy="ftp://x:1")
        assert result.outcome is Outcome.ERROR
        assert "Прокси" in result.message

    async def test_sends_code_and_keeps_client(self, manager):
        result = await manager.start_telegram(OWNER, "+79991234567", None)
        assert result.outcome is Outcome.CODE_SENT
        pending = manager.get(OWNER)
        assert pending is not None
        assert pending.phone_code_hash == "hash-abc"
        # Клиент обязан остаться подключённым: phone_code_hash привязан
        # к этому соединению.
        assert pending.client.connected
        assert not pending.client.disconnected

    async def test_banned_number_reported(self, manager):
        manager.fake_client.send_code_error = PhoneNumberBannedError(request=None)
        result = await manager.start_telegram(OWNER, "+79991234567", None)
        assert result.outcome is Outcome.ERROR
        assert "заблокирован" in result.message

    async def test_published_api_id_is_explained(self, manager):
        """Засвеченный ключ Telegram ограничивает — это нужно назвать прямо."""
        manager.fake_client.send_code_error = ApiIdPublishedFloodError(request=None)
        result = await manager.start_telegram(OWNER, "+79991234567", None)
        assert result.outcome is Outcome.ERROR
        assert "API_ID_PUBLISHED_FLOOD" in result.message
        assert "my.telegram.org" in result.message

    async def test_invalid_api_id_is_explained(self, manager):
        manager.fake_client.send_code_error = ApiIdInvalidError(request=None)
        result = await manager.start_telegram(OWNER, "+79991234567", None)
        assert result.outcome is Outcome.ERROR
        assert "api_id" in result.message


class TestKeypad:
    async def test_digits_accumulate(self, manager):
        await manager.start_telegram(OWNER, "+79991234567", None)
        for digit in "12345":
            manager.push_digit(OWNER, digit)
        assert manager.get(OWNER).digits == "12345"

    async def test_backspace_removes_last(self, manager):
        await manager.start_telegram(OWNER, "+79991234567", None)
        manager.push_digit(OWNER, "1")
        manager.push_digit(OWNER, "2")
        manager.backspace(OWNER)
        assert manager.get(OWNER).digits == "1"

    async def test_length_is_capped(self, manager):
        await manager.start_telegram(OWNER, "+79991234567", None)
        for _ in range(20):
            manager.push_digit(OWNER, "9")
        assert len(manager.get(OWNER).digits) == 7

    def test_push_without_session_returns_none(self, manager):
        assert manager.push_digit(OWNER, "1") is None


class TestSubmitCode:
    async def test_short_code_rejected_before_request(self, manager):
        await manager.start_telegram(OWNER, "+79991234567", None)
        manager.push_digit(OWNER, "1")
        result = await manager.submit_code(OWNER)
        assert result.outcome is Outcome.INVALID_CODE
        assert manager.fake_client.sign_in_calls == []

    async def test_successful_login_saves_encrypted_session(self, manager, db, app_settings):
        await manager.start_telegram(OWNER, "+79991234567", None)
        for digit in "12345":
            manager.push_digit(OWNER, digit)
        result = await manager.submit_code(OWNER)

        assert result.outcome is Outcome.SIGNED_IN
        async with db.session() as session:
            account = await AccountRepo(session, OWNER).first_active()
        assert account.tg_user_id == FakeMe.id
        assert account.username == "ivanov"
        # В базе лежит шифротекст, а не сама строка сессии.
        assert b"1BVtsFAKESESSION" not in account.session_enc
        cipher = SessionCipher(app_settings.session_encryption_key)
        assert cipher.decrypt(account.session_enc) == "1BVtsFAKESESSION"

    async def test_session_closed_after_success(self, manager):
        await manager.start_telegram(OWNER, "+79991234567", None)
        for digit in "12345":
            manager.push_digit(OWNER, digit)
        await manager.submit_code(OWNER)
        assert manager.get(OWNER) is None

    async def test_invalid_code_clears_digits_and_keeps_session(self, manager):
        manager.fake_client._effects = [PhoneCodeInvalidError(request=None)]
        await manager.start_telegram(OWNER, "+79991234567", None)
        for digit in "12345":
            manager.push_digit(OWNER, digit)
        result = await manager.submit_code(OWNER)

        assert result.outcome is Outcome.INVALID_CODE
        pending = manager.get(OWNER)
        assert pending is not None
        assert pending.digits == ""

    async def test_expired_code_ends_session_with_hint(self, manager):
        manager.fake_client._effects = [PhoneCodeExpiredError(request=None)]
        await manager.start_telegram(OWNER, "+79991234567", None)
        for digit in "12345":
            manager.push_digit(OWNER, digit)
        result = await manager.submit_code(OWNER)

        assert result.outcome is Outcome.CODE_EXPIRED
        assert "кнопками" in result.message
        assert manager.get(OWNER) is None

    async def test_two_factor_switches_to_password_stage(self, manager):
        manager.fake_client._effects = [SessionPasswordNeededError(request=None)]
        await manager.start_telegram(OWNER, "+79991234567", None)
        for digit in "12345":
            manager.push_digit(OWNER, digit)
        result = await manager.submit_code(OWNER)

        assert result.outcome is Outcome.NEEDS_PASSWORD
        assert manager.get(OWNER).stage is Stage.PASSWORD

    async def test_password_completes_login(self, manager, db):
        manager.fake_client._effects = [SessionPasswordNeededError(request=None)]
        await manager.start_telegram(OWNER, "+79991234567", None)
        for digit in "12345":
            manager.push_digit(OWNER, digit)
        await manager.submit_code(OWNER)

        result = await manager.submit_password(OWNER, "мойпароль")
        assert result.outcome is Outcome.SIGNED_IN
        async with db.session() as session:
            assert await AccountRepo(session, OWNER).first_active() is not None

    async def test_password_without_stage_is_rejected(self, manager):
        await manager.start_telegram(OWNER, "+79991234567", None)
        result = await manager.submit_password(OWNER, "пароль")
        assert result.outcome is Outcome.ERROR

    async def test_submit_without_session(self, manager):
        result = await manager.submit_code(OWNER)
        assert result.outcome is Outcome.ERROR
        assert "истекла" in result.message


class TestCancel:
    async def test_cancel_disconnects_client(self, manager):
        await manager.start_telegram(OWNER, "+79991234567", None)
        client = manager.get(OWNER).client
        await manager.cancel(OWNER)
        assert client.disconnected
        assert manager.get(OWNER) is None

    async def test_restart_replaces_previous_attempt(self, manager):
        await manager.start_telegram(OWNER, "+79991234567", None)
        first = manager.get(OWNER).client
        await manager.start_telegram(OWNER, "+79991234568", None)
        assert first.disconnected
