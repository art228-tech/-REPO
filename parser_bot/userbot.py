"""Работа с аккаунтом Telegram через Telethon: вход и проверка чатов."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    ChatAdminRequiredError,
    ChatWriteForbiddenError,
    FloodWaitError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    SessionPasswordNeededError,
    UserAlreadyParticipantError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetFullChannelRequest, JoinChannelRequest
from telethon.tl.functions.messages import (
    CheckChatInviteRequest,
    GetFullChatRequest,
    ImportChatInviteRequest,
)
from telethon.tl import types as tl

from .config import Config
from .utils import ChatRef, extract_refs, normalize

log = logging.getLogger(__name__)


@dataclass
class ProbeResult:
    # 'clean' | 'captcha' | 'op' | 'error'
    status: str
    members: int = 0
    title: str = ""
    chat_id: Optional[int] = None
    reason: str = ""
    op_refs: list[ChatRef] = field(default_factory=list)


class LoginError(Exception):
    pass


class UserBot:
    """Обёртка над одним аккаунтом Telegram."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client: Optional[TelegramClient] = None
        # временное состояние для входа по номеру
        self._pending_phone: Optional[str] = None
        self._pending_hash: Optional[str] = None
        self._lock = asyncio.Lock()

    # ---------- ВХОД ----------
    def _new_client(self, session: str = "") -> TelegramClient:
        if not self.cfg.api_id or not self.cfg.api_hash:
            raise LoginError(
                "Не заданы API_ID/API_HASH. Укажите их в .env (my.telegram.org)."
            )
        return TelegramClient(StringSession(session), self.cfg.api_id, self.cfg.api_hash)

    async def login_with_session(self, session_str: str) -> str:
        client = self._new_client(session_str.strip())
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise LoginError("Сессия недействительна или истекла.")
        await self._set_client(client)
        return await self.account_name()

    async def start_phone_login(self, phone: str) -> None:
        client = self._new_client()
        await client.connect()
        try:
            sent = await client.send_code_request(phone)
        except Exception as e:  # noqa: BLE001
            await client.disconnect()
            raise LoginError(f"Не удалось отправить код: {e}")
        self.client = client
        self._pending_phone = phone
        self._pending_hash = sent.phone_code_hash

    async def submit_code(self, code: str) -> Optional[str]:
        """Возвращает имя аккаунта при успехе. Бросает LoginError('2FA') если нужен пароль."""
        if not self.client or not self._pending_phone:
            raise LoginError("Сначала отправьте номер телефона.")
        try:
            await self.client.sign_in(
                self._pending_phone, code=code, phone_code_hash=self._pending_hash
            )
        except SessionPasswordNeededError:
            raise LoginError("2FA")
        except Exception as e:  # noqa: BLE001
            raise LoginError(f"Неверный код: {e}")
        return await self._finish_login()

    async def submit_password(self, password: str) -> str:
        if not self.client:
            raise LoginError("Нет активной сессии входа.")
        try:
            await self.client.sign_in(password=password)
        except Exception as e:  # noqa: BLE001
            raise LoginError(f"Неверный пароль 2FA: {e}")
        return await self._finish_login()

    async def _finish_login(self) -> str:
        self._pending_phone = None
        self._pending_hash = None
        return await self.account_name()

    async def _set_client(self, client: TelegramClient) -> None:
        if self.client and self.client is not client:
            try:
                await self.client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self.client = client

    async def is_authorized(self) -> bool:
        return bool(self.client and self.client.is_connected()
                    and await self.client.is_user_authorized())

    async def account_name(self) -> str:
        if not self.client:
            return "?"
        me = await self.client.get_me()
        name = " ".join(filter(None, [getattr(me, "first_name", ""), getattr(me, "last_name", "")]))
        uname = f" @{me.username}" if getattr(me, "username", None) else ""
        return f"{name}{uname} (id {me.id})".strip()

    def session_string(self) -> str:
        if self.client and isinstance(self.client.session, StringSession):
            return self.client.session.save()
        return ""

    async def logout(self) -> None:
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self.client = None

    # ---------- ПРОВЕРКА ЧАТА ----------
    async def _resolve_and_join(self, ref: ChatRef):
        """Возвращает entity чата, при необходимости вступая в него."""
        client = self.client
        assert client is not None
        if ref.kind == "invite":
            inv_hash = ref.ident.split(":", 1)[1]
            try:
                updates = await client(ImportChatInviteRequest(inv_hash))
                chat = updates.chats[0]
                return chat
            except UserAlreadyParticipantError:
                info = await client(CheckChatInviteRequest(inv_hash))
                return getattr(info, "chat", None)
            except (InviteHashExpiredError, InviteHashInvalidError) as e:
                raise LoginError(f"Инвайт недействителен: {e}")
        else:
            username = ref.ident.lstrip("@")
            try:
                entity = await client.get_entity(username)
            except (UsernameInvalidError, UsernameNotOccupiedError, ValueError) as e:
                raise LoginError(f"Юзернейм не найден: {e}")
            # вступаем, чтобы иметь возможность писать и считать участников
            try:
                await client(JoinChannelRequest(entity))
            except Exception:  # noqa: BLE001 — уже участник / не канал и т.п.
                pass
            return entity

    async def _members_count(self, entity) -> int:
        client = self.client
        assert client is not None
        try:
            if isinstance(entity, (tl.Channel,)):
                full = await client(GetFullChannelRequest(entity))
                return int(getattr(full.full_chat, "participants_count", 0) or 0)
            if isinstance(entity, (tl.Chat,)):
                full = await client(GetFullChatRequest(entity.id))
                return int(getattr(full.full_chat, "participants_count", 0) or 0)
        except Exception as e:  # noqa: BLE001
            log.debug("members_count failed: %s", e)
        return int(getattr(entity, "participants_count", 0) or 0)

    @staticmethod
    def _collect_button_data(message) -> list[str]:
        out: list[str] = []
        markup = getattr(message, "reply_markup", None)
        rows = getattr(markup, "rows", None) or []
        for row in rows:
            for btn in getattr(row, "buttons", []) or []:
                txt = getattr(btn, "text", None)
                if txt:
                    out.append(txt)
                url = getattr(btn, "url", None)
                if url:
                    out.append(url)
        return out

    def _classify(self, blob: str, extra_links: list[str]) -> tuple[str, list[ChatRef], str]:
        low = blob.lower()
        for kw in self.cfg.captcha_keywords:
            if kw in low:
                return "captcha", [], f"найдено ключевое слово капчи: '{kw}'"
        op_refs = extract_refs(blob, extra=extra_links)
        for kw in self.cfg.op_keywords:
            if kw in low:
                return "op", op_refs, f"найдено ключевое слово ОП: '{kw}'"
        # если ответ содержит ссылки на каналы для подписки без явных слов —
        # тоже считаем за ОП.
        if op_refs:
            return "op", op_refs, "в ответе обнаружены ссылки на каналы (вероятно ОП)"
        return "clean", [], "ограничений не обнаружено"

    async def probe(self, ref: ChatRef) -> ProbeResult:
        """Заходит в чат, ставит точку, анализирует реакцию модератора."""
        async with self._lock:
            client = self.client
            if not client or not await client.is_user_authorized():
                return ProbeResult(status="error", reason="нет авторизованного аккаунта")

            try:
                entity = await self._resolve_and_join(ref)
            except LoginError as e:
                return ProbeResult(status="error", reason=str(e))
            except FloodWaitError as e:
                return ProbeResult(status="error", reason=f"FloodWait {e.seconds}s при входе")
            except (ChannelPrivateError,) as e:
                return ProbeResult(status="error", reason=f"приватный/недоступный чат: {e}")
            except Exception as e:  # noqa: BLE001
                return ProbeResult(status="error", reason=f"вход не удался: {e}")

            if entity is None:
                return ProbeResult(status="error", reason="не удалось получить чат")

            title = getattr(entity, "title", "") or ""
            chat_id = getattr(entity, "id", None)
            members = await self._members_count(entity)

            me = await client.get_me()
            try:
                sent = await client.send_message(entity, ".")
            except (ChatWriteForbiddenError, ChatAdminRequiredError) as e:
                return ProbeResult(
                    status="op", members=members, title=title, chat_id=chat_id,
                    reason=f"писать запрещено без условий: {e}",
                )
            except FloodWaitError as e:
                return ProbeResult(status="error", members=members, title=title,
                                   chat_id=chat_id, reason=f"FloodWait {e.seconds}s")
            except Exception as e:  # noqa: BLE001
                return ProbeResult(status="error", members=members, title=title,
                                   chat_id=chat_id, reason=f"отправка не удалась: {e}")

            await asyncio.sleep(self.cfg.probe_wait)

            # Собираем реакцию: свежие сообщения + ответы на нашу точку.
            texts: list[str] = []
            links: list[str] = []
            our_msg_alive = False
            try:
                recent = await client.get_messages(entity, limit=20)
            except Exception:  # noqa: BLE001
                recent = []

            for msg in recent:
                if msg.id == sent.id:
                    our_msg_alive = True
                    continue
                # интересны сообщения после нашей точки или адресованные нам
                is_reply_to_us = getattr(msg, "reply_to_msg_id", None) == sent.id
                mentions_us = bool(getattr(msg, "mentioned", False))
                if msg.id > sent.id or is_reply_to_us or mentions_us:
                    if msg.message:
                        texts.append(msg.message)
                    links.extend(self._collect_button_data(msg))

            blob = "\n".join(texts)
            status, op_refs, reason = self._classify(blob, links)

            # если нашу точку удалили и при этом никаких внятных слов нет —
            # это, скорее всего, антиспам/капча.
            if not our_msg_alive and status == "clean":
                status, op_refs, reason = "captcha", [], "сообщение удалено антиспамом"

            # чистим за собой
            if our_msg_alive:
                try:
                    await client.delete_messages(entity, [sent.id])
                except Exception:  # noqa: BLE001
                    pass

            return ProbeResult(
                status=status,
                members=members,
                title=title,
                chat_id=chat_id,
                reason=reason,
                op_refs=op_refs,
            )
