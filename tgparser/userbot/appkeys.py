"""Получение api_id и api_hash через my.telegram.org.

Метода для регистрации приложения в MTProto не существует — Telegram отдаёт
ключи только через веб-портал. Портал при этом устроен на обычных HTML-формах
с сессионной кукой, поэтому пройти их программой можно.

Замкнутый круг разрывается участием человека: код подтверждения приходит
внутрь Telegram, и его вводит пользователь. Дальше создание приложения и
чтение ключей идут без него.

Портал не рассчитан на автоматические обращения и на серверные IP регулярно
отвечает безликой ошибкой, особенно когда страна адреса не совпадает со
страной номера. Поэтому у всего этого обязателен ручной путь: пользователь
может ввести свои ключи руками.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

BASE = "https://my.telegram.org"
TIMEOUT = aiohttp.ClientTimeout(total=30)

# Портал охотнее отвечает клиенту, похожему на браузер.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": BASE,
    "Referer": f"{BASE}/auth",
    "X-Requested-With": "XMLHttpRequest",
}

API_ID_RE = re.compile(r"^\d{4,12}$")
# Код портала — не цифровой: приходит строка вида 3QvmDbabncs. Поле в форме
# называется password, а не code, и это именно пароль сеанса на сайте.
PORTAL_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{5,40}$")
API_HASH_RE = re.compile(r"^[0-9a-f]{32}$")
SPAN_RE = re.compile(
    r"<span[^>]*class=\"[^\"]*uneditable-input[^\"]*\"[^>]*>(.*?)</span>",
    re.IGNORECASE | re.DOTALL,
)
CSRF_RE = re.compile(
    r"<input[^>]*name=[\"']hash[\"'][^>]*value=[\"']([0-9a-f]+)[\"']", re.IGNORECASE
)

APP_DEFAULTS = {
    "app_title": "Chat Parser",
    "app_shortname": "chatparser",
    # Пустой URL портал может счесть незаполненным полем и отказать безликой
    # ошибкой, поэтому подставляем валидный адрес.
    "app_url": "https://telegram.org",
    # Не "other": в форме этот вариант подписан «Other (specify in
    # description)», то есть требует назвать платформу в описании.
    "app_platform": "android",
    "app_desc": "Personal tool for collecting chat participants on Android",
}


class PortalError(RuntimeError):
    """Ошибка, текст которой можно показывать пользователю как есть."""


MANUAL_HINT = (
    "Ключи можно получить вручную: my.telegram.org → вход по номеру → "
    "API development tools → заполнить любые поля → Create application. "
    "Оттуда скопируйте App api_id и App api_hash."
)


@dataclass(slots=True)
class AppKeys:
    api_id: int
    api_hash: str


@dataclass(slots=True)
class PortalLogin:
    """Незавершённый вход в портал: между запросом кода и его вводом."""

    phone: str
    random_hash: str


def normalize_portal_code(raw: str) -> str | None:
    """Код с my.telegram.org, как его прислал пользователь.

    Регистр значащий, поэтому только убираем пробелы и оформление.
    """
    if not raw:
        return None
    cleaned = raw.strip().strip(".,;:")
    cleaned = "".join(cleaned.split())
    return cleaned if PORTAL_CODE_RE.match(cleaned) else None


def extract_keys(html: str) -> AppKeys | None:
    """Вытащить ключи со страницы приложений.

    Ищем по форме значений, а не по порядку полей: тогда перестановка блоков
    на странице ничего не сломает.
    """
    values = [re.sub(r"<[^>]+>", "", raw).strip() for raw in SPAN_RE.findall(html)]
    api_id = next((v for v in values if API_ID_RE.match(v)), None)
    api_hash = next((v for v in values if API_HASH_RE.match(v.lower())), None)
    if api_id is None or api_hash is None:
        return None
    return AppKeys(api_id=int(api_id), api_hash=api_hash.lower())


def extract_csrf(html: str) -> str | None:
    match = CSRF_RE.search(html)
    return match.group(1) if match else None


def looks_like_error(body: str) -> bool:
    """Портал отвечает то текстом, то JSON, поэтому проверяем оба вида."""
    stripped = body.strip().strip('"').lower()
    if stripped in {"error", "false"} or stripped.startswith("error"):
        return True
    # Ответы вида {"error": "..."} по первому символу за ошибку не сойдут.
    return stripped.startswith("{") and '"error"' in stripped


class PortalClient:
    """Один сеанс работы с my.telegram.org."""

    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> PortalClient:
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=TIMEOUT, headers=HEADERS, cookie_jar=aiohttp.CookieJar()
            )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()

    @property
    def _http(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise PortalError("Сессия портала не открыта")
        return self._session

    async def _post(self, path: str, data: dict[str, str]) -> str:
        try:
            async with self._http.post(f"{BASE}{path}", data=data) as response:
                return await response.text()
        except aiohttp.ClientError as exc:
            raise PortalError(f"Портал my.telegram.org недоступен: {exc}") from exc

    async def _get(self, path: str) -> str:
        try:
            async with self._http.get(f"{BASE}{path}") as response:
                return await response.text()
        except aiohttp.ClientError as exc:
            raise PortalError(f"Портал my.telegram.org недоступен: {exc}") from exc

    async def request_code(self, phone: str) -> PortalLogin:
        """Попросить портал отправить код в Telegram."""
        body = await self._post("/auth/send_password", {"phone": phone})
        match = re.search(r'"random_hash"\s*:\s*"([^"]+)"', body)
        if match is None:
            if "invalid" in body.lower() or "not found" in body.lower():
                raise PortalError(
                    "Портал не знает такого номера. Он должен совпадать с номером "
                    "аккаунта, который вы подключаете."
                )
            logger.warning("send_password вернул неожиданное: %s", body[:200])
            raise PortalError(
                "Портал отказался отправить код. Так бывает с серверных адресов. "
                + MANUAL_HINT
            )
        return PortalLogin(phone=phone, random_hash=match.group(1))

    async def login(self, login: PortalLogin, code: str) -> None:
        body = await self._post(
            "/auth/login",
            {"phone": login.phone, "random_hash": login.random_hash, "password": code},
        )
        if looks_like_error(body):
            raise PortalError(
                "Портал не принял код. Проверьте, что вводите код из сообщения "
                "от Telegram, и что он не устарел."
            )

    async def obtain_keys(self) -> AppKeys:
        """Прочитать существующее приложение или создать новое."""
        html = await self._get("/apps")

        keys = extract_keys(html)
        if keys is not None:
            logger.info("Найдено готовое приложение с api_id %s", keys.api_id)
            return keys

        csrf = extract_csrf(html)
        if csrf is None:
            raise PortalError(
                "Портал не отдал форму создания приложения. Он часто так делает "
                "в ответ на запросы с серверных адресов. " + MANUAL_HINT
            )

        created = await self._post("/apps/create", {"hash": csrf, **APP_DEFAULTS})
        if looks_like_error(created):
            raise PortalError(
                "Портал отклонил создание приложения. " + MANUAL_HINT
            )

        keys = extract_keys(await self._get("/apps"))
        if keys is None:
            raise PortalError(
                "Приложение создано, но ключи со страницы прочитать не удалось. "
                + MANUAL_HINT
            )
        logger.info("Создано приложение с api_id %s", keys.api_id)
        return keys
