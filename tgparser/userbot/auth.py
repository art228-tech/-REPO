"""Вход в аккаунт: код набирается инлайн-клавиатурой.

Сервер Telegram инвалидирует код, если тот отправлен сообщением внутри
Telegram: сообщение от служебного пользователя 777000 сканируется на
последовательность из 5-7 цифр, и при пересылке или отправке код гасится
через ``account.invalidateSignInCodes``. Нажатие инлайн-кнопки — это
callback query, а не сообщение, поэтому набор цифр кнопками код не гасит.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from telethon.errors import (
    ApiIdInvalidError,
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeEmptyError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    RPCError,
    SessionPasswordNeededError,
)

from tgparser.config import Settings
from tgparser.crypto import SessionCipher
from tgparser.userbot.client import new_client
from tgparser.userbot.proxy import ProxyError, parse_proxy

logger = logging.getLogger(__name__)

CODE_LENGTH_MAX = 7
PENDING_TTL = timedelta(minutes=10)


class Stage(str, enum.Enum):
    CODE = "code"
    PASSWORD = "password"
    DONE = "done"


class Outcome(str, enum.Enum):
    CODE_SENT = "code_sent"
    SIGNED_IN = "signed_in"
    NEEDS_PASSWORD = "needs_password"
    INVALID_CODE = "invalid_code"
    CODE_EXPIRED = "code_expired"
    INVALID_PASSWORD = "invalid_password"
    ERROR = "error"


@dataclass(slots=True)
class AuthResult:
    outcome: Outcome
    message: str
    account_id: int | None = None
    username: str | None = None


@dataclass(slots=True)
class PendingAuth:
    client: Any
    phone: str
    phone_code_hash: str
    proxy: str | None = None
    digits: str = ""
    stage: Stage = Stage.CODE
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def expired(self) -> bool:
        return datetime.now(timezone.utc) - self.created_at > PENDING_TTL

    @property
    def masked(self) -> str:
        """Отображение набранного кода: цифры и прочерки на месте пустых."""
        shown = " ".join(self.digits) if self.digits else ""
        placeholder = " ".join("·" * max(0, 5 - len(self.digits)))
        return f"{shown} {placeholder}".strip() if placeholder else shown


def normalize_phone(raw: str) -> str | None:
    """Привести номер к виду +79991234567."""
    if not raw:
        return None
    cleaned = "".join(ch for ch in raw if ch.isdigit())
    if not 8 <= len(cleaned) <= 15:
        return None
    return f"+{cleaned}"


class AuthManager:
    """Держит незавершённые авторизации.

    Клиент обязан оставаться подключённым между отправкой кода и входом:
    ``phone_code_hash`` привязан к этому соединению, и пересоздание клиента
    делает код непригодным.
    """

    def __init__(self, settings: Settings, cipher: SessionCipher, db: Any) -> None:
        self._settings = settings
        self._cipher = cipher
        self._db = db
        self._pending: dict[int, PendingAuth] = {}

    def get(self, owner_id: int) -> PendingAuth | None:
        pending = self._pending.get(owner_id)
        if pending is not None and pending.expired:
            return None
        return pending

    async def start(self, owner_id: int, phone: str, proxy: str | None = None) -> AuthResult:
        await self.cancel(owner_id)

        normalized = normalize_phone(phone)
        if normalized is None:
            return AuthResult(
                Outcome.ERROR,
                "Не похоже на номер. Пришлите в формате +79991234567.",
            )
        try:
            parse_proxy(proxy)
        except ProxyError as exc:
            return AuthResult(Outcome.ERROR, f"Прокси: {exc}")

        client = new_client(self._settings, proxy=proxy)
        try:
            await client.connect()
            sent = await client.send_code_request(normalized)
        except ApiIdInvalidError:
            await self._close(client)
            return AuthResult(
                Outcome.ERROR,
                "API_ID или API_HASH неверные. Проверьте значения с my.telegram.org.",
            )
        except PhoneNumberInvalidError:
            await self._close(client)
            return AuthResult(Outcome.ERROR, "Telegram не знает такого номера.")
        except PhoneNumberBannedError:
            await self._close(client)
            return AuthResult(Outcome.ERROR, "Номер заблокирован в Telegram.")
        except FloodWaitError as exc:
            await self._close(client)
            return AuthResult(
                Outcome.ERROR,
                f"Слишком много попыток входа. Telegram просит подождать {exc.seconds} с.",
            )
        except RPCError as exc:
            await self._close(client)
            logger.warning("send_code_request не удался: %s", exc)
            return AuthResult(Outcome.ERROR, f"Не удалось запросить код: {exc}")

        self._pending[owner_id] = PendingAuth(
            client=client,
            phone=normalized,
            phone_code_hash=sent.phone_code_hash,
            proxy=proxy,
        )
        return AuthResult(Outcome.CODE_SENT, "Код отправлен.")

    def push_digit(self, owner_id: int, digit: str) -> PendingAuth | None:
        pending = self.get(owner_id)
        if pending is None or pending.stage is not Stage.CODE:
            return None
        if len(pending.digits) < CODE_LENGTH_MAX:
            pending.digits += digit
        return pending

    def backspace(self, owner_id: int) -> PendingAuth | None:
        pending = self.get(owner_id)
        if pending is None or pending.stage is not Stage.CODE:
            return None
        pending.digits = pending.digits[:-1]
        return pending

    def clear_digits(self, owner_id: int) -> PendingAuth | None:
        pending = self.get(owner_id)
        if pending is None:
            return None
        pending.digits = ""
        return pending

    async def submit_code(self, owner_id: int) -> AuthResult:
        pending = self.get(owner_id)
        if pending is None:
            return AuthResult(Outcome.ERROR, "Сессия входа истекла, начните заново.")
        if len(pending.digits) < 5:
            return AuthResult(Outcome.INVALID_CODE, "Код короче пяти цифр.")

        try:
            await pending.client.sign_in(
                phone=pending.phone,
                code=pending.digits,
                phone_code_hash=pending.phone_code_hash,
            )
        except SessionPasswordNeededError:
            pending.stage = Stage.PASSWORD
            pending.digits = ""
            return AuthResult(
                Outcome.NEEDS_PASSWORD,
                "На аккаунте включена двухфакторная защита. Пришлите облачный пароль "
                "сообщением — я удалю его сразу после проверки.",
            )
        except (PhoneCodeInvalidError, PhoneCodeEmptyError):
            pending.digits = ""
            return AuthResult(Outcome.INVALID_CODE, "Код неверный. Наберите заново.")
        except PhoneCodeExpiredError:
            await self.cancel(owner_id)
            return AuthResult(
                Outcome.CODE_EXPIRED,
                "Код просрочен или погашен Telegram. Запросите новый и не "
                "отправляйте его сообщением — только кнопками.",
            )
        except FloodWaitError as exc:
            await self.cancel(owner_id)
            return AuthResult(
                Outcome.ERROR, f"Telegram просит подождать {exc.seconds} с."
            )
        except RPCError as exc:
            logger.warning("sign_in не удался: %s", exc)
            return AuthResult(Outcome.ERROR, f"Вход не удался: {exc}")

        return await self._finish(owner_id, pending)

    async def submit_password(self, owner_id: int, password: str) -> AuthResult:
        pending = self.get(owner_id)
        if pending is None:
            return AuthResult(Outcome.ERROR, "Сессия входа истекла, начните заново.")
        if pending.stage is not Stage.PASSWORD:
            return AuthResult(Outcome.ERROR, "Пароль сейчас не запрашивается.")

        try:
            await pending.client.sign_in(password=password)
        except PasswordHashInvalidError:
            return AuthResult(Outcome.INVALID_PASSWORD, "Пароль неверный, попробуйте снова.")
        except FloodWaitError as exc:
            await self.cancel(owner_id)
            return AuthResult(Outcome.ERROR, f"Telegram просит подождать {exc.seconds} с.")
        except RPCError as exc:
            logger.warning("Вход по паролю не удался: %s", exc)
            return AuthResult(Outcome.ERROR, f"Вход не удался: {exc}")

        return await self._finish(owner_id, pending)

    async def _finish(self, owner_id: int, pending: PendingAuth) -> AuthResult:
        from tgparser.db.repo import AccountRepo

        try:
            me = await pending.client.get_me()
        except RPCError as exc:
            return AuthResult(Outcome.ERROR, f"Вход прошёл, но профиль не читается: {exc}")

        session_string = pending.client.session.save()
        encrypted = self._cipher.encrypt(session_string)

        async with self._db.session() as session:
            account = await AccountRepo(session).upsert_session(
                phone=pending.phone,
                session_enc=encrypted,
                tg_user_id=getattr(me, "id", None),
                username=getattr(me, "username", None),
                proxy=pending.proxy,
            )
            account_id = account.id

        pending.stage = Stage.DONE
        await self.cancel(owner_id)

        name = getattr(me, "first_name", None) or getattr(me, "username", None) or pending.phone
        return AuthResult(
            Outcome.SIGNED_IN,
            f"Аккаунт {name} подключён.",
            account_id=account_id,
            username=getattr(me, "username", None),
        )

    async def cancel(self, owner_id: int) -> None:
        pending = self._pending.pop(owner_id, None)
        if pending is not None:
            await self._close(pending.client)

    async def close_all(self) -> None:
        for owner_id in list(self._pending):
            await self.cancel(owner_id)

    @staticmethod
    async def _close(client: Any) -> None:
        try:
            await client.disconnect()
        except Exception:
            logger.debug("Не удалось закрыть клиент", exc_info=True)
