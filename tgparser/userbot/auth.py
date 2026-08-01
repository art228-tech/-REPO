"""Подключение аккаунта: ключи приложения, затем вход по коду.

Код набирается инлайн-клавиатурой, а не присылается сообщением: сервер
Telegram гасит коды, отправленные внутри мессенджера — он сканирует сообщения
от служебного пользователя 777000 на последовательность из 5-7 цифр и
вызывает ``account.invalidateSignInCodes``. Нажатие инлайн-кнопки это
callback query, а не сообщение, поэтому набор кнопками код не гасит.

Путей два. Автоматический: бот сам проходит my.telegram.org и забирает
api_id с api_hash, а человек только вводит код от портала. Ручной: ключи
вводятся руками. Ручной нужен потому, что портал регулярно отказывает
запросам с серверных адресов.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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
from tgparser.userbot.appkeys import AppKeys, PortalClient, PortalError, PortalLogin
from tgparser.userbot.client import MissingAppKeysError, new_client
from tgparser.userbot.proxy import ProxyError, parse_proxy

logger = logging.getLogger(__name__)

CODE_LENGTH_MAX = 7
PENDING_TTL = timedelta(minutes=15)


class Stage(enum.StrEnum):
    PORTAL_CODE = "portal_code"
    CODE = "code"
    PASSWORD = "password"
    DONE = "done"


class Outcome(enum.StrEnum):
    PORTAL_CODE_SENT = "portal_code_sent"
    KEYS_READY = "keys_ready"
    CODE_SENT = "code_sent"
    SIGNED_IN = "signed_in"
    NEEDS_PASSWORD = "needs_password"
    INVALID_CODE = "invalid_code"
    CODE_EXPIRED = "code_expired"
    INVALID_PASSWORD = "invalid_password"
    PORTAL_FAILED = "portal_failed"
    ERROR = "error"


@dataclass(slots=True)
class AuthResult:
    outcome: Outcome
    message: str
    account_id: int | None = None
    username: str | None = None
    keys: AppKeys | None = None


@dataclass(slots=True)
class PendingAuth:
    phone: str
    stage: Stage
    proxy: str | None = None
    digits: str = ""

    client: Any | None = None
    phone_code_hash: str | None = None

    portal: PortalClient | None = None
    portal_login: PortalLogin | None = None
    keys: AppKeys | None = None

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def expired(self) -> bool:
        return datetime.now(UTC) - self.created_at > PENDING_TTL

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


def parse_keys(raw: str) -> AppKeys | None:
    """Разобрать пару ключей, введённую руками одним сообщением."""
    import re

    if not raw:
        return None
    tokens = [t for t in re.split(r"[\s,;:]+", raw.strip()) if t]
    api_id = next((t for t in tokens if t.isdigit() and 4 <= len(t) <= 12), None)
    api_hash = next((t for t in tokens if re.fullmatch(r"[0-9a-fA-F]{32}", t)), None)
    if api_id is None or api_hash is None:
        return None
    return AppKeys(api_id=int(api_id), api_hash=api_hash.lower())


class AuthManager:
    """Держит незавершённые подключения.

    Клиент Telethon обязан оставаться подключённым между отправкой кода и
    входом: ``phone_code_hash`` привязан к этому соединению, и пересоздание
    клиента делает код непригодным.
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

    # --- путь через портал ---

    async def start_portal(
        self, owner_id: int, phone: str, proxy: str | None = None
    ) -> AuthResult:
        normalized = self._check_phone(phone)
        if isinstance(normalized, AuthResult):
            return normalized
        proxy_error = self._check_proxy(proxy)
        if proxy_error is not None:
            return proxy_error

        await self.cancel(owner_id)
        portal = PortalClient()
        await portal.__aenter__()
        try:
            login = await portal.request_code(normalized)
        except PortalError as exc:
            await portal.__aexit__(None, None, None)
            return AuthResult(Outcome.PORTAL_FAILED, str(exc))

        self._pending[owner_id] = PendingAuth(
            phone=normalized,
            stage=Stage.PORTAL_CODE,
            proxy=proxy,
            portal=portal,
            portal_login=login,
        )
        return AuthResult(
            Outcome.PORTAL_CODE_SENT,
            "my.telegram.org отправил код в Telegram — придёт сообщением "
            "от служебного аккаунта. Наберите его кнопками.",
        )

    async def submit_portal_code(self, owner_id: int) -> AuthResult:
        pending = self.get(owner_id)
        if pending is None or pending.portal is None or pending.portal_login is None:
            return AuthResult(Outcome.ERROR, "Сессия входа истекла, начните заново.")
        if len(pending.digits) < 5:
            return AuthResult(Outcome.INVALID_CODE, "Код короче пяти цифр.")

        code = pending.digits
        pending.digits = ""
        try:
            await pending.portal.login(pending.portal_login, code)
            keys = await pending.portal.obtain_keys()
        except PortalError as exc:
            return AuthResult(Outcome.PORTAL_FAILED, str(exc))

        pending.keys = keys
        await pending.portal.__aexit__(None, None, None)
        pending.portal = None
        pending.portal_login = None

        result = await self._send_tg_code(owner_id, pending)
        if result.outcome is not Outcome.CODE_SENT:
            return result
        return AuthResult(
            Outcome.CODE_SENT,
            f"Ключи получены: api_id <code>{keys.api_id}</code>.\n\n"
            "Теперь Telegram отправил код для входа в аккаунт — наберите его кнопками.",
            keys=keys,
        )

    # --- путь со своими или общими ключами ---

    async def start_telegram(
        self,
        owner_id: int,
        phone: str,
        keys: AppKeys | None,
        proxy: str | None = None,
    ) -> AuthResult:
        normalized = self._check_phone(phone)
        if isinstance(normalized, AuthResult):
            return normalized
        proxy_error = self._check_proxy(proxy)
        if proxy_error is not None:
            return proxy_error

        await self.cancel(owner_id)
        pending = PendingAuth(
            phone=normalized, stage=Stage.CODE, proxy=proxy, keys=keys
        )
        self._pending[owner_id] = pending
        return await self._send_tg_code(owner_id, pending)

    async def _send_tg_code(self, owner_id: int, pending: PendingAuth) -> AuthResult:
        try:
            client = new_client(self._settings, keys=pending.keys, proxy=pending.proxy)
        except MissingAppKeysError as exc:
            await self.cancel(owner_id)
            return AuthResult(Outcome.ERROR, str(exc))

        pending.client = client
        try:
            await client.connect()
            sent = await client.send_code_request(pending.phone)
        except ApiIdInvalidError:
            await self.cancel(owner_id)
            return AuthResult(
                Outcome.ERROR,
                "Telegram не принял api_id и api_hash. Проверьте значения "
                "с my.telegram.org.",
            )
        except PhoneNumberInvalidError:
            await self.cancel(owner_id)
            return AuthResult(Outcome.ERROR, "Telegram не знает такого номера.")
        except PhoneNumberBannedError:
            await self.cancel(owner_id)
            return AuthResult(Outcome.ERROR, "Номер заблокирован в Telegram.")
        except FloodWaitError as exc:
            await self.cancel(owner_id)
            return AuthResult(
                Outcome.ERROR,
                f"Слишком много попыток входа. Telegram просит подождать {exc.seconds} с.",
            )
        except RPCError as exc:
            await self.cancel(owner_id)
            logger.warning("send_code_request не удался: %s", exc)
            return AuthResult(Outcome.ERROR, f"Не удалось запросить код: {exc}")

        pending.phone_code_hash = sent.phone_code_hash
        pending.stage = Stage.CODE
        pending.digits = ""
        return AuthResult(Outcome.CODE_SENT, "Код отправлен.")

    # --- клавиатура ---

    def push_digit(self, owner_id: int, digit: str) -> PendingAuth | None:
        pending = self.get(owner_id)
        if pending is None or pending.stage not in (Stage.PORTAL_CODE, Stage.CODE):
            return None
        if len(pending.digits) < CODE_LENGTH_MAX:
            pending.digits += digit
        return pending

    def backspace(self, owner_id: int) -> PendingAuth | None:
        pending = self.get(owner_id)
        if pending is None or pending.stage not in (Stage.PORTAL_CODE, Stage.CODE):
            return None
        pending.digits = pending.digits[:-1]
        return pending

    async def submit(self, owner_id: int) -> AuthResult:
        """Отправить набранный код — портала или Telegram, смотря по стадии."""
        pending = self.get(owner_id)
        if pending is None:
            return AuthResult(Outcome.ERROR, "Сессия входа истекла, начните заново.")
        if pending.stage is Stage.PORTAL_CODE:
            return await self.submit_portal_code(owner_id)
        return await self.submit_code(owner_id)

    # --- вход в Telegram ---

    async def submit_code(self, owner_id: int) -> AuthResult:
        pending = self.get(owner_id)
        if pending is None or pending.client is None:
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
            return AuthResult(Outcome.ERROR, f"Telegram просит подождать {exc.seconds} с.")
        except RPCError as exc:
            logger.warning("sign_in не удался: %s", exc)
            return AuthResult(Outcome.ERROR, f"Вход не удался: {exc}")

        return await self._finish(owner_id, pending)

    async def submit_password(self, owner_id: int, password: str) -> AuthResult:
        pending = self.get(owner_id)
        if pending is None or pending.client is None:
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
        # api_hash тоже секрет, поэтому в базе он лежит зашифрованным.
        api_hash_enc = (
            self._cipher.encrypt(pending.keys.api_hash) if pending.keys else None
        )

        async with self._db.session() as session:
            account = await AccountRepo(session, owner_id).upsert_session(
                phone=pending.phone,
                session_enc=self._cipher.encrypt(session_string),
                tg_user_id=getattr(me, "id", None),
                username=getattr(me, "username", None),
                proxy=pending.proxy,
                api_id=pending.keys.api_id if pending.keys else None,
                api_hash_enc=api_hash_enc,
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
            keys=pending.keys,
        )

    # --- вспомогательное ---

    def _check_phone(self, phone: str) -> str | AuthResult:
        normalized = normalize_phone(phone)
        if normalized is None:
            return AuthResult(
                Outcome.ERROR, "Не похоже на номер. Пришлите в формате +79991234567."
            )
        return normalized

    def _check_proxy(self, proxy: str | None) -> AuthResult | None:
        try:
            parse_proxy(proxy)
        except ProxyError as exc:
            return AuthResult(Outcome.ERROR, f"Прокси: {exc}")
        return None

    async def cancel(self, owner_id: int) -> None:
        pending = self._pending.pop(owner_id, None)
        if pending is None:
            return
        if pending.client is not None:
            try:
                await pending.client.disconnect()
            except Exception:
                logger.debug("Не удалось закрыть клиент", exc_info=True)
        if pending.portal is not None:
            try:
                await pending.portal.__aexit__(None, None, None)
            except Exception:
                logger.debug("Не удалось закрыть портал", exc_info=True)

    async def close_all(self) -> None:
        for owner_id in list(self._pending):
            await self.cancel(owner_id)
