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
    # 'clean' | 'captcha' | 'op' | 'not_chat' | 'error'
    status: str
    members: int = 0
    title: str = ""
    chat_id: Optional[int] = None
    reason: str = ""
    msgs_per_day: float = 0.0
    op_refs: list[ChatRef] = field(default_factory=list)


@dataclass
class Resolved:
    entity: object = None          # telethon entity, если доступен/мы уже в чате
    writable: bool = False         # это группа/супергруппа, куда можно писать
    title: str = ""
    members: int = 0
    kind: str = "unknown"          # megagroup|group|broadcast|bot|user|unknown
    joinable: bool = True
    error: Optional[str] = None


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
    @staticmethod
    def _entity_writable(entity) -> tuple[bool, str]:
        """Только группы/супергруппы считаем 'чатом, куда можно писать'."""
        if isinstance(entity, tl.Chat):
            # базовая группа (но не удалённая/мигрировавшая)
            if getattr(entity, "deactivated", False):
                return False, "unknown"
            return True, "group"
        if isinstance(entity, tl.Channel):
            if getattr(entity, "megagroup", False) or getattr(entity, "gigagroup", False):
                return True, "megagroup"
            return False, "broadcast"  # вещательный канал — не чат
        if isinstance(entity, tl.User):
            return False, "bot" if getattr(entity, "bot", False) else "user"
        return False, "unknown"

    async def _resolve(self, ref: ChatRef) -> Resolved:
        """Определяет тип объекта (чат/канал/бот/юзер) БЕЗ вступления, где можно."""
        client = self.client
        assert client is not None
        if ref.kind == "invite":
            inv_hash = ref.ident.split(":", 1)[1]
            try:
                info = await client(CheckChatInviteRequest(inv_hash))
            except (InviteHashExpiredError, InviteHashInvalidError) as e:
                return Resolved(error=f"инвайт недействителен: {e}")
            except Exception as e:  # noqa: BLE001
                return Resolved(error=f"не удалось проверить инвайт: {e}")
            chat = getattr(info, "chat", None)
            if chat is not None:  # ChatInviteAlready / ChatInvitePeek — мы уже в чате
                writable, kind = self._entity_writable(chat)
                return Resolved(
                    entity=chat, writable=writable, kind=kind,
                    title=getattr(chat, "title", "") or "",
                    members=int(getattr(chat, "participants_count", 0) or 0),
                )
            # ChatInvite — ещё не вступили
            title = getattr(info, "title", "") or ""
            members = int(getattr(info, "participants_count", 0) or 0)
            is_broadcast = getattr(info, "broadcast", False)
            is_megagroup = getattr(info, "megagroup", False)
            request_needed = getattr(info, "request_needed", False)
            if is_broadcast and not is_megagroup:
                return Resolved(writable=False, kind="broadcast", title=title, members=members)
            if request_needed:
                return Resolved(writable=True, kind="megagroup", title=title,
                                members=members, joinable=False,
                                error="нужна заявка на вступление")
            return Resolved(writable=True, kind="megagroup" if is_megagroup else "group",
                            title=title, members=members)
        # публичный username
        username = ref.ident.lstrip("@")
        try:
            entity = await client.get_entity(username)
        except (UsernameInvalidError, UsernameNotOccupiedError, ValueError) as e:
            return Resolved(error=f"юзернейм не найден: {e}")
        except Exception as e:  # noqa: BLE001
            return Resolved(error=f"не удалось получить объект: {e}")
        writable, kind = self._entity_writable(entity)
        title = getattr(entity, "title", "") or getattr(entity, "username", "") or ""
        return Resolved(
            entity=entity, writable=writable, kind=kind, title=title,
            members=int(getattr(entity, "participants_count", 0) or 0),
        )

    async def _ensure_joined(self, ref: ChatRef, res: Resolved):
        """Вступает в чат, если ещё не вступили. Возвращает entity."""
        client = self.client
        assert client is not None
        if ref.kind == "invite" and res.entity is None:
            inv_hash = ref.ident.split(":", 1)[1]
            try:
                updates = await client(ImportChatInviteRequest(inv_hash))
                return updates.chats[0]
            except UserAlreadyParticipantError:
                info = await client(CheckChatInviteRequest(inv_hash))
                return getattr(info, "chat", None)
        entity = res.entity
        if isinstance(entity, tl.Channel):
            try:
                await client(JoinChannelRequest(entity))
            except Exception:  # noqa: BLE001 — уже участник и т.п.
                pass
        return entity

    async def _messages_per_day(self, entity, msgs=None) -> float:
        """Оценка активности: сообщений в сутки по последним сообщениям."""
        client = self.client
        assert client is not None
        if msgs is None:
            try:
                msgs = await client.get_messages(entity, limit=self.cfg.activity_sample)
            except Exception:  # noqa: BLE001
                return 0.0
        dates = [m.date for m in msgs if getattr(m, "date", None)]
        if len(dates) < 2:
            return float(len(dates))
        span = (max(dates) - min(dates)).total_seconds()
        if span <= 0:
            return float(len(dates))
        return round((len(dates) - 1) / (span / 86400.0), 1)

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

            # 1) Определяем тип объекта. Всё, что не группа/супергруппа — мусор.
            try:
                res = await self._resolve(ref)
            except FloodWaitError as e:
                return ProbeResult(status="error", reason=f"FloodWait {e.seconds}s при входе")
            except ChannelPrivateError as e:
                return ProbeResult(status="error", reason=f"приватный/недоступный: {e}")
            except Exception as e:  # noqa: BLE001
                return ProbeResult(status="error", reason=f"resolve не удался: {e}")

            if res.error and not res.writable:
                return ProbeResult(status="error", title=res.title, members=res.members,
                                   reason=res.error)
            if not res.writable:
                return ProbeResult(
                    status="not_chat", title=res.title, members=res.members,
                    reason=f"не чат (тип: {res.kind}) — в мусор",
                )
            if not res.joinable:
                return ProbeResult(status="error", title=res.title, members=res.members,
                                   reason=res.error or "нельзя вступить")

            # 2) Это писабельный чат — вступаем.
            try:
                entity = await self._ensure_joined(ref, res)
            except FloodWaitError as e:
                return ProbeResult(status="error", title=res.title, members=res.members,
                                   reason=f"FloodWait {e.seconds}s при вступлении")
            except Exception as e:  # noqa: BLE001
                return ProbeResult(status="error", title=res.title, members=res.members,
                                   reason=f"вступление не удалось: {e}")

            if entity is None:
                return ProbeResult(status="error", reason="не удалось получить чат")

            title = getattr(entity, "title", "") or res.title
            chat_id = getattr(entity, "id", None)
            members = await self._members_count(entity) or res.members

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
                recent = await client.get_messages(
                    entity, limit=max(20, self.cfg.activity_sample)
                )
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

            # активность (сообщений/сутки) — считаем по выборке без нашей точки
            msgs_per_day = await self._messages_per_day(
                entity, [m for m in recent if m.id != sent.id]
            )

            return ProbeResult(
                status=status,
                members=members,
                title=title,
                chat_id=chat_id,
                reason=reason,
                msgs_per_day=msgs_per_day,
                op_refs=op_refs,
            )
