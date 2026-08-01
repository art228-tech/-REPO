from __future__ import annotations

import pytest
from telethon.errors import (
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    SessionPasswordNeededError,
)

from tgparser.config import Settings
from tgparser.crypto import SessionCipher, generate_key
from tgparser.db.repo import AccountRepo
from tgparser.userbot import auth as auth_module
from tgparser.userbot.auth import AuthManager, Outcome, PendingAuth, Stage, normalize_phone

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
        OWNER_ID=OWNER,
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


class TestPendingAuthDisplay:
    def test_masks_remaining_positions(self):
        pending = PendingAuth(client=None, phone="+7", phone_code_hash="h", digits="12")
        assert pending.masked.startswith("1 2")
        assert "·" in pending.masked

    def test_full_code_has_no_placeholder(self):
        pending = PendingAuth(client=None, phone="+7", phone_code_hash="h", digits="12345")
        assert "·" not in pending.masked


class TestStart:
    async def test_rejects_bad_phone(self, manager):
        result = await manager.start(OWNER, "не номер")
        assert result.outcome is Outcome.ERROR
        assert "формате" in result.message

    async def test_rejects_bad_proxy(self, manager):
        result = await manager.start(OWNER, "+79991234567", proxy="ftp://x:1")
        assert result.outcome is Outcome.ERROR
        assert "Прокси" in result.message

    async def test_sends_code_and_keeps_client(self, manager):
        result = await manager.start(OWNER, "+79991234567")
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
        result = await manager.start(OWNER, "+79991234567")
        assert result.outcome is Outcome.ERROR
        assert "заблокирован" in result.message


class TestKeypad:
    async def test_digits_accumulate(self, manager):
        await manager.start(OWNER, "+79991234567")
        for digit in "12345":
            manager.push_digit(OWNER, digit)
        assert manager.get(OWNER).digits == "12345"

    async def test_backspace_removes_last(self, manager):
        await manager.start(OWNER, "+79991234567")
        manager.push_digit(OWNER, "1")
        manager.push_digit(OWNER, "2")
        manager.backspace(OWNER)
        assert manager.get(OWNER).digits == "1"

    async def test_length_is_capped(self, manager):
        await manager.start(OWNER, "+79991234567")
        for _ in range(20):
            manager.push_digit(OWNER, "9")
        assert len(manager.get(OWNER).digits) == 7

    def test_push_without_session_returns_none(self, manager):
        assert manager.push_digit(OWNER, "1") is None


class TestSubmitCode:
    async def test_short_code_rejected_before_request(self, manager):
        await manager.start(OWNER, "+79991234567")
        manager.push_digit(OWNER, "1")
        result = await manager.submit_code(OWNER)
        assert result.outcome is Outcome.INVALID_CODE
        assert manager.fake_client.sign_in_calls == []

    async def test_successful_login_saves_encrypted_session(self, manager, db, app_settings):
        await manager.start(OWNER, "+79991234567")
        for digit in "12345":
            manager.push_digit(OWNER, digit)
        result = await manager.submit_code(OWNER)

        assert result.outcome is Outcome.SIGNED_IN
        async with db.session() as session:
            account = await AccountRepo(session).first_active()
        assert account.tg_user_id == FakeMe.id
        assert account.username == "ivanov"
        # В базе лежит шифротекст, а не сама строка сессии.
        assert b"1BVtsFAKESESSION" not in account.session_enc
        cipher = SessionCipher(app_settings.session_encryption_key)
        assert cipher.decrypt(account.session_enc) == "1BVtsFAKESESSION"

    async def test_session_closed_after_success(self, manager):
        await manager.start(OWNER, "+79991234567")
        for digit in "12345":
            manager.push_digit(OWNER, digit)
        await manager.submit_code(OWNER)
        assert manager.get(OWNER) is None

    async def test_invalid_code_clears_digits_and_keeps_session(self, manager):
        manager.fake_client._effects = [PhoneCodeInvalidError(request=None)]
        await manager.start(OWNER, "+79991234567")
        for digit in "12345":
            manager.push_digit(OWNER, digit)
        result = await manager.submit_code(OWNER)

        assert result.outcome is Outcome.INVALID_CODE
        pending = manager.get(OWNER)
        assert pending is not None
        assert pending.digits == ""

    async def test_expired_code_ends_session_with_hint(self, manager):
        manager.fake_client._effects = [PhoneCodeExpiredError(request=None)]
        await manager.start(OWNER, "+79991234567")
        for digit in "12345":
            manager.push_digit(OWNER, digit)
        result = await manager.submit_code(OWNER)

        assert result.outcome is Outcome.CODE_EXPIRED
        assert "кнопками" in result.message
        assert manager.get(OWNER) is None

    async def test_two_factor_switches_to_password_stage(self, manager):
        manager.fake_client._effects = [SessionPasswordNeededError(request=None)]
        await manager.start(OWNER, "+79991234567")
        for digit in "12345":
            manager.push_digit(OWNER, digit)
        result = await manager.submit_code(OWNER)

        assert result.outcome is Outcome.NEEDS_PASSWORD
        assert manager.get(OWNER).stage is Stage.PASSWORD

    async def test_password_completes_login(self, manager, db):
        manager.fake_client._effects = [SessionPasswordNeededError(request=None)]
        await manager.start(OWNER, "+79991234567")
        for digit in "12345":
            manager.push_digit(OWNER, digit)
        await manager.submit_code(OWNER)

        result = await manager.submit_password(OWNER, "мойпароль")
        assert result.outcome is Outcome.SIGNED_IN
        async with db.session() as session:
            assert await AccountRepo(session).first_active() is not None

    async def test_password_without_stage_is_rejected(self, manager):
        await manager.start(OWNER, "+79991234567")
        result = await manager.submit_password(OWNER, "пароль")
        assert result.outcome is Outcome.ERROR

    async def test_submit_without_session(self, manager):
        result = await manager.submit_code(OWNER)
        assert result.outcome is Outcome.ERROR
        assert "истекла" in result.message


class TestCancel:
    async def test_cancel_disconnects_client(self, manager):
        await manager.start(OWNER, "+79991234567")
        client = manager.get(OWNER).client
        await manager.cancel(OWNER)
        assert client.disconnected
        assert manager.get(OWNER) is None

    async def test_restart_replaces_previous_attempt(self, manager):
        await manager.start(OWNER, "+79991234567")
        first = manager.get(OWNER).client
        await manager.start(OWNER, "+79991234568")
        assert first.disconnected
