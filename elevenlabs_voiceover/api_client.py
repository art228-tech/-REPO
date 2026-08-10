"""HTTP-клиент ElevenLabs.

Работаем напрямую с REST, без официального SDK: так проще контролировать
ретраи, точно классифицировать ошибки и писать в лог ровно то, что нужно для
разбора проблем (и ничего лишнего).
"""

from __future__ import annotations

import base64
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import requests

from .errors import (
    AuthError,
    Cancelled,
    ElevenLabsError,
    InvalidResponse,
    NetworkError,
    ProxyFailure,
    QuotaExceeded,
    RateLimited,
    ScopeError,
    ServerError,
    ValidationFailed,
    VoiceLimitReached,
)
from .logging_setup import get_logger, redact, register_secret

log = get_logger("api")

BASE_URL = "https://api.elevenlabs.io"

#: Значения detail.status, по которым API однозначно опознаёт причину отказа.
_STATUS_QUOTA = {"quota_exceeded", "max_character_limit_exceeded"}
_STATUS_AUTH = {"invalid_api_key", "missing_api_key", "api_key_disabled", "expired_api_key"}
_STATUS_SCOPE = {"missing_permissions", "invalid_api_key_permissions", "ip_not_allowed"}
_STATUS_VOICE_LIMIT = {"voice_limit_reached", "max_voice_limit_reached", "voice_add_edit_limit_reached"}


@dataclass
class Subscription:
    tier: str
    status: str
    character_count: int
    character_limit: int
    voice_slots_used: int
    voice_limit: int
    next_reset_unix: Optional[int]
    can_use_instant_voice_cloning: bool
    raw: Dict[str, Any]

    @property
    def credits_left(self) -> int:
        return max(0, self.character_limit - self.character_count)

    @property
    def voice_slots_left(self) -> int:
        return max(0, self.voice_limit - self.voice_slots_used)

    def summary(self) -> str:
        return (
            f"тариф {self.tier} ({self.status}), "
            f"кредитов {self.credits_left} из {self.character_limit}, "
            f"слотов голосов свободно {self.voice_slots_left} из {self.voice_limit}"
        )


@dataclass
class ModelInfo:
    model_id: str
    name: str
    can_do_text_to_speech: bool
    max_chars_per_request: int
    cost_multiplier: float
    languages: List[str]

    def label(self) -> str:
        rate = f"{self.cost_multiplier:g} кред./символ"
        return f"{self.name or self.model_id} — {rate}"


@dataclass
class VoicePreview:
    generated_voice_id: str
    audio: bytes
    duration_secs: float
    language: Optional[str]


@dataclass
class TtsResult:
    audio: bytes
    request_id: Optional[str]
    characters: int


class ElevenLabsClient:
    def __init__(
        self,
        api_key: str,
        *,
        timeout: int = 180,
        max_retries: int = 5,
        cancel_event: Optional[threading.Event] = None,
        base_url: str = BASE_URL,
        proxy_url: str = "",
        ignore_system_proxy: bool = False,
    ) -> None:
        key = (api_key or "").strip()
        if not key:
            raise AuthError("API-ключ не задан")
        register_secret(key)

        self._key = key
        self._timeout = timeout
        self._max_retries = max_retries
        self._cancel = cancel_event or threading.Event()
        self._base_url = base_url.rstrip("/")

        self._session = requests.Session()
        self._session.headers.update(
            {
                "xi-api-key": key,
                "User-Agent": "elevenlabs-voiceover/1.0 (+desktop)",
                "Accept": "*/*",
            }
        )
        apply_proxy(self._session, proxy_url, ignore_system_proxy)

        log.debug("Соединение с %s, %s", self._base_url, describe_route(proxy_url, ignore_system_proxy))

    # ------------------------------------------------------------------
    def close(self) -> None:
        try:
            self._session.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> ElevenLabsClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    def _check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise Cancelled()

    def _sleep(self, seconds: float) -> None:
        """Пауза, прерываемая кнопкой «Стоп»."""
        deadline = time.monotonic() + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if self._cancel.wait(min(0.2, remaining)):
                raise Cancelled()

    # ------------------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        expect_binary: bool = False,
    ) -> Tuple[Any, Dict[str, str]]:
        url = f"{self._base_url}{path}"
        attempt = 0

        while True:
            self._check_cancelled()
            attempt += 1
            started = time.monotonic()
            try:
                response = self._session.request(
                    method,
                    url,
                    json=json_body,
                    params=params,
                    timeout=(15, self._timeout),
                )
            except requests.exceptions.ProxyError as exc:
                error: ElevenLabsError = ProxyFailure(
                    f"Не удалось выйти через прокси: {_explain_network_error(exc)}", endpoint=path
                )
            except requests.exceptions.Timeout as exc:
                error = NetworkError(f"Таймаут запроса: {_explain_network_error(exc)}", endpoint=path)
            except requests.exceptions.ConnectionError as exc:
                error = NetworkError(f"Нет связи с API: {_explain_network_error(exc)}", endpoint=path)
            except requests.exceptions.RequestException as exc:
                error = NetworkError(f"Ошибка запроса: {_explain_network_error(exc)}", endpoint=path)
            else:
                elapsed = time.monotonic() - started
                size = len(response.content or b"")
                log.debug(
                    "%s %s -> %s за %.2f с, %d байт (попытка %d)",
                    method,
                    path,
                    response.status_code,
                    elapsed,
                    size,
                    attempt,
                )
                if response.ok:
                    headers = {k.lower(): v for k, v in response.headers.items()}
                    if expect_binary:
                        return response.content, headers
                    if not response.content:
                        return None, headers
                    try:
                        return response.json(), headers
                    except ValueError:
                        error = _describe_bad_body(response, path)
                        log.warning("%s", error.message)
                else:
                    error = self._classify(response, path)

            if error.fatal or not error.retryable or attempt > self._max_retries:
                if isinstance(error, RateLimited) and attempt > self._max_retries:
                    log.error("Лимит частоты запросов не удалось переждать за %d попыток", attempt - 1)
                raise error

            delay = self._backoff_delay(attempt, error)
            log.warning(
                "%s %s: %s. Повтор %d/%d через %.1f с",
                method,
                path,
                error.message,
                attempt,
                self._max_retries,
                delay,
            )
            self._sleep(delay)

    def _backoff_delay(self, attempt: int, error: ElevenLabsError) -> float:
        if isinstance(error, RateLimited) and error.retry_after:
            # Сервер сам сказал, сколько ждать — доверяем ему.
            return min(120.0, float(error.retry_after))
        base = min(60.0, 1.5 * (2 ** (attempt - 1)))
        return base * (0.7 + 0.6 * random.random())

    # ------------------------------------------------------------------
    def _classify(self, response: requests.Response, path: str) -> ElevenLabsError:
        code = response.status_code
        detail_status, message, payload = _parse_error_body(response)
        text = message or response.reason or "неизвестная ошибка"

        if detail_status in _STATUS_QUOTA:
            return QuotaExceeded(
                f"Кредиты на аккаунте закончились: {text}", status_code=code, payload=payload, endpoint=path
            )
        if detail_status in _STATUS_VOICE_LIMIT:
            return VoiceLimitReached(
                f"Достигнут лимит слотов для голосов: {text}", status_code=code, payload=payload, endpoint=path
            )
        if detail_status in _STATUS_SCOPE:
            return ScopeError(
                "Ключу не хватает прав или запрос пришёл с неразрешённого IP. "
                f"Проверьте разрешения ключа (нужны Text to Speech и Voices): {text}",
                status_code=code,
                payload=payload,
                endpoint=path,
            )
        if detail_status in _STATUS_AUTH:
            return AuthError(f"Проблема с API-ключом: {text}", status_code=code, payload=payload, endpoint=path)

        if code == 429:
            return RateLimited(
                f"Слишком много запросов: {text}",
                retry_after=_retry_after_seconds(response),
                status_code=code,
                payload=payload,
                endpoint=path,
            )
        if code in (401, 403):
            # ElevenLabs отдаёт 401 и на протухший ключ, и на исчерпанную квоту.
            # Если detail.status не пришёл, разделяем по тексту сообщения.
            lowered = text.lower()
            if "quota" in lowered or "credit" in lowered:
                return QuotaExceeded(f"Кредиты закончились: {text}", status_code=code, payload=payload, endpoint=path)
            if "permission" in lowered or "not allowed" in lowered or "forbidden" in lowered:
                return ScopeError(
                    f"Недостаточно прав у ключа: {text}", status_code=code, payload=payload, endpoint=path
                )
            return AuthError(f"Ключ отклонён: {text}", status_code=code, payload=payload, endpoint=path)
        if code == 422:
            return ValidationFailed(f"Запрос отклонён валидацией: {text}", status_code=code, payload=payload, endpoint=path)
        if code >= 500:
            return ServerError(f"Ошибка на стороне ElevenLabs: {text}", status_code=code, payload=payload, endpoint=path)
        return ElevenLabsError(text, status_code=code, payload=payload, endpoint=path)

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------
    def get_subscription(self) -> Subscription:
        data, _ = self._request("GET", "/v1/user/subscription")
        if not isinstance(data, dict):
            raise ElevenLabsError("Неожиданный ответ на запрос подписки", endpoint="/v1/user/subscription")
        return Subscription(
            tier=str(data.get("tier", "unknown")),
            status=str(data.get("status", "unknown")),
            character_count=int(data.get("character_count") or 0),
            character_limit=int(data.get("character_limit") or 0),
            voice_slots_used=int(data.get("voice_slots_used") or 0),
            voice_limit=int(data.get("voice_limit") or 0),
            next_reset_unix=data.get("next_character_count_reset_unix"),
            can_use_instant_voice_cloning=bool(data.get("can_use_instant_voice_cloning")),
            raw=data,
        )

    def list_models(self) -> List[ModelInfo]:
        data, _ = self._request("GET", "/v1/models")
        if not isinstance(data, list):
            raise ElevenLabsError("Неожиданный ответ на запрос моделей", endpoint="/v1/models")
        models: List[ModelInfo] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            rates = item.get("model_rates") or {}
            multiplier = rates.get("character_cost_multiplier")
            discount = rates.get("cost_discount_multiplier", 1)
            try:
                cost = float(multiplier if multiplier is not None else 1.0) * float(discount or 1.0)
            except (TypeError, ValueError):
                cost = 1.0
            models.append(
                ModelInfo(
                    model_id=str(item.get("model_id", "")),
                    name=str(item.get("name") or item.get("model_id") or ""),
                    can_do_text_to_speech=bool(item.get("can_do_text_to_speech")),
                    max_chars_per_request=int(item.get("maximum_text_length_per_request") or 0),
                    cost_multiplier=cost,
                    languages=[
                        str(lang.get("language_id"))
                        for lang in (item.get("languages") or [])
                        if isinstance(lang, dict) and lang.get("language_id")
                    ],
                )
            )
        return [m for m in models if m.model_id]

    def list_voices(self) -> List[Dict[str, Any]]:
        data, _ = self._request("GET", "/v1/voices")
        if isinstance(data, dict):
            voices = data.get("voices")
            if isinstance(voices, list):
                return [v for v in voices if isinstance(v, dict)]
        return []

    # ------------------------------------------------------------------
    def design_voice(
        self,
        description: str,
        *,
        model_id: str = "eleven_multilingual_ttv_v2",
        preview_text: Optional[str] = None,
        auto_generate_text: bool = False,
        guidance_scale: float = 5.0,
        output_format: str = "mp3_44100_128",
        seed: Optional[int] = None,
    ) -> List[VoicePreview]:
        """Сгенерировать варианты голоса по текстовому описанию.

        Кредиты списываются один раз по длине preview-текста, независимо от
        того, что в ответе приходит несколько вариантов.
        """
        body: Dict[str, Any] = {
            "voice_description": description,
            "model_id": model_id,
            "guidance_scale": guidance_scale,
        }
        if auto_generate_text:
            body["auto_generate_text"] = True
        else:
            body["text"] = preview_text
        if seed is not None:
            body["seed"] = seed

        data, _ = self._request(
            "POST",
            "/v1/text-to-voice/design",
            json_body=body,
            params={"output_format": output_format},
        )
        if not isinstance(data, dict):
            raise ElevenLabsError("Неожиданный ответ Voice Design", endpoint="/v1/text-to-voice/design")

        previews: List[VoicePreview] = []
        for item in data.get("previews") or []:
            if not isinstance(item, dict):
                continue
            generated_id = item.get("generated_voice_id")
            if not generated_id:
                continue
            try:
                audio = base64.b64decode(item.get("audio_base_64") or "")
            except (ValueError, TypeError):
                audio = b""
            previews.append(
                VoicePreview(
                    generated_voice_id=str(generated_id),
                    audio=audio,
                    duration_secs=float(item.get("duration_secs") or 0.0),
                    language=item.get("language"),
                )
            )
        if not previews:
            raise ElevenLabsError(
                "Voice Design не вернул ни одного варианта голоса", endpoint="/v1/text-to-voice/design"
            )
        return previews

    def create_voice_from_preview(
        self,
        *,
        voice_name: str,
        voice_description: str,
        generated_voice_id: str,
        played_not_selected: Optional[List[str]] = None,
        labels: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "voice_name": voice_name,
            "voice_description": voice_description,
            "generated_voice_id": generated_voice_id,
        }
        if played_not_selected:
            body["played_not_selected_voice_ids"] = played_not_selected
        if labels:
            body["labels"] = labels

        data, _ = self._request("POST", "/v1/text-to-voice", json_body=body)
        if not isinstance(data, dict) or not data.get("voice_id"):
            raise ElevenLabsError("API не вернул voice_id при сохранении голоса", endpoint="/v1/text-to-voice")
        return data

    def delete_voice(self, voice_id: str) -> None:
        self._request("DELETE", f"/v1/voices/{voice_id}")

    # ------------------------------------------------------------------
    def text_to_speech(
        self,
        voice_id: str,
        text: str,
        *,
        model_id: str,
        output_format: str = "mp3_44100_128",
        voice_settings: Optional[Dict[str, Any]] = None,
        previous_text: Optional[str] = None,
        next_text: Optional[str] = None,
        previous_request_ids: Optional[List[str]] = None,
        language_code: Optional[str] = None,
    ) -> TtsResult:
        body: Dict[str, Any] = {"text": text, "model_id": model_id}
        if voice_settings:
            body["voice_settings"] = voice_settings
        if previous_text:
            body["previous_text"] = previous_text
        if next_text:
            body["next_text"] = next_text
        if previous_request_ids:
            # API принимает не более трёх идентификаторов.
            body["previous_request_ids"] = previous_request_ids[-3:]
        if language_code:
            body["language_code"] = language_code

        audio, headers = self._request(
            "POST",
            f"/v1/text-to-speech/{voice_id}",
            json_body=body,
            params={"output_format": output_format},
            expect_binary=True,
        )
        if not audio:
            raise ElevenLabsError("API вернул пустой аудиоответ", endpoint="/v1/text-to-speech")
        return TtsResult(
            audio=audio,
            request_id=headers.get("request-id") or headers.get("x-request-id"),
            characters=len(text),
        )


_HTML_MARKERS = (b"<!doctype html", b"<html", b"<head", b"<body", b"<!--")

#: Признаки страницы ElevenLabs про запрет обслуживания отдельных стран. Она
#: приходит с кодом 200 вместо ответа API, и без разбора тела выглядит просто
#: как «ответ не разобрался».
_GEO_BLOCK_MARKERS = (
    b"restrict access",
    b"specific countries",
    b"not available in your country",
    b"unsupported region",
)


def hide_credentials(url: str) -> str:
    """Убрать логин и пароль из адреса прокси перед записью в лог.

    Разбор строковый, без urlsplit: его свойство port бросает исключение на
    любом непонятном адресе, а функция вызывается из конструктора клиента и
    обязана отработать при любом содержимом поля.
    """
    text = (url or "").strip()
    if not text:
        return ""

    scheme, separator, rest = text.partition("://")
    if not separator:
        scheme, rest = "", text

    if "@" in rest:
        rest = rest.rsplit("@", 1)[1]
    rest = rest.split("/", 1)[0]

    return f"{scheme}://{rest}" if scheme else rest


def apply_proxy(session: requests.Session, proxy_url: str = "", ignore_system_proxy: bool = False) -> None:
    """Настроить, каким путём сессия пойдёт в сеть."""
    if ignore_system_proxy:
        # Сломанный или устаревший системный прокси — частая причина обрывов,
        # и обойти его должно быть возможно, не трогая настройки Windows.
        session.trust_env = False

    proxy = (proxy_url or "").strip()
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
        session.trust_env = False


def describe_route(proxy_url: str = "", ignore_system_proxy: bool = False) -> str:
    """Человекочитаемое описание пути в сеть — для лога и отчёта.

    Вызывается при создании клиента, поэтому не имеет права бросить исключение:
    иначе непонятная строка в поле прокси уронит запуск ещё до первого запроса.
    """
    try:
        proxy = (proxy_url or "").strip()
        if proxy:
            return f"через свой прокси {hide_credentials(proxy)}"
        if ignore_system_proxy:
            return "напрямую, системный прокси отключён"
        system = safe_proxy_summary()
        return f"через системный прокси ({system})" if system else "напрямую"
    except Exception as exc:  # noqa: BLE001
        log.debug("Не удалось описать путь в сеть: %s", exc)
        return "путь в сеть определить не удалось"


def safe_proxy_summary() -> str:
    """Прокси, через которые пойдут запросы, без логинов и паролей."""
    try:
        proxies = requests.utils.getproxies()
    except Exception:  # noqa: BLE001 - опрос системных настроек не должен ронять запуск
        return ""

    parts = []
    for scheme in ("http", "https"):
        url = proxies.get(scheme)
        if not url:
            continue
        try:
            split = urlsplit(url if "://" in url else f"//{url}")
            host = split.hostname or "?"
            port = f":{split.port}" if split.port else ""
            parts.append(f"{scheme} через {host}{port}")
        except ValueError:
            parts.append(f"{scheme} через (адрес не разобран)")
    return ", ".join(parts)


def _describe_bad_body(response: requests.Response, path: str) -> InvalidResponse:
    """Объяснить, что пришло вместо JSON, и на кого это похоже.

    Без разбора тела в логе остаётся только «Expecting value: line 1 column 1»,
    по которому невозможно понять, кто именно вмешался в соединение.
    """
    content_type = (response.headers.get("Content-Type") or "не указан").split(";")[0].strip()
    body = response.content or b""
    head = body[:4096].lower()

    snippet = redact(
        body[:300].decode("utf-8", errors="replace").replace("\r", " ").replace("\n", " ").strip()
    )

    header_names = {k.lower() for k in response.headers}
    if any(marker in head for marker in _GEO_BLOCK_MARKERS):
        cause = (
            "ElevenLabs ответил своей справкой об ограничениях по странам: сервис не "
            "обслуживает страну, из которой пришёл запрос. API-ключ здесь ни при чём. "
            "Нужно сменить страну в VPN — подойдут США или Европа. Убедитесь также, что "
            "через VPN идёт весь трафик, а не только выбранные сайты."
        )
    elif b"cloudflare" in head or "cf-ray" in header_names or "cf-mitigated" in header_names:
        cause = (
            "Похоже на проверочную страницу Cloudflare: запрос сочли подозрительным. "
            "Чаще всего дело в VPN или прокси, через который идёт соединение."
        )
    elif any(marker in head for marker in _HTML_MARKERS) or content_type.startswith("text/html"):
        cause = (
            "Вместо ответа API пришла веб-страница. Так бывает, когда соединение читает "
            "кто-то посередине: антивирус с проверкой HTTPS, корпоративный прокси, VPN "
            "или страница-заглушка провайдера."
        )
    else:
        cause = "Тело ответа не похоже ни на JSON, ни на веб-страницу."

    proxy = safe_proxy_summary()
    proxy_note = f" В системе настроен прокси: {proxy}." if proxy else ""

    return InvalidResponse(
        f"{cause}{proxy_note} Тип содержимого {content_type}, {len(body)} байт. "
        f"Начало ответа: «{snippet}»",
        status_code=response.status_code,
        payload=snippet,
        endpoint=path,
    )


#: Порядок перебора схем при автоподборе. socks5h идёт раньше socks5: разрешение
#: имён на стороне прокси нужно ровно там, где прокси и понадобился.
PROXY_SCHEME_CANDIDATES = ("http", "socks5h", "socks5")


def swap_proxy_scheme(proxy_url: str, scheme: str) -> str:
    """Заменить схему в адресе прокси, оставив всё остальное."""
    text = (proxy_url or "").strip()
    if not text:
        return ""
    _, separator, rest = text.partition("://")
    return f"{scheme}://{rest if separator else text}"


def detect_proxy_scheme(
    proxy_url: str,
    timeout: int = 8,
    base_url: str = BASE_URL,
) -> Optional[str]:
    """Подобрать схему, с которой прокси действительно отвечает.

    Продавцы обычно дают адрес без схемы, а http и socks5 внешне неотличимы.
    Перебрать три варианта быстрее и надёжнее, чем предлагать человеку гадать.
    """
    proxy = (proxy_url or "").strip()
    if not proxy:
        return None

    url = f"{base_url.rstrip('/')}/v1/models"
    for scheme in PROXY_SCHEME_CANDIDATES:
        candidate = swap_proxy_scheme(proxy, scheme)
        session = requests.Session()
        session.trust_env = False
        session.proxies = {"http": candidate, "https": candidate}
        try:
            session.get(url, timeout=(timeout, timeout))
        except requests.exceptions.RequestException as exc:
            log.debug("Прокси по схеме %s не отозвался: %s", scheme, str(exc)[:150])
            continue
        else:
            # Любой ответ означает, что через прокси мы вышли наружу: код
            # ответа тут неважен, важно что соединение состоялось.
            log.info("Прокси отвечает по схеме %s", scheme)
            return scheme
        finally:
            session.close()

    log.warning("Ни одна из схем %s не подошла к прокси", ", ".join(PROXY_SCHEME_CANDIDATES))
    return None


#: Служебная страница Cloudflare: отдаёт адрес и страну выхода простым текстом.
TRACE_URL = "https://www.cloudflare.com/cdn-cgi/trace"

#: Страны, из которых ElevenLabs не обслуживает запросы. Список неполный и может
#: меняться, поэтому служит только подсказкой в проверке соединения.
_LIKELY_BLOCKED = {"RU", "BY", "IR", "KP", "SY", "CU", "VE"}


def outbound_address(timeout: int = 10, proxy_url: str = "", ignore_system_proxy: bool = False) -> str:
    """Узнать, с какого адреса и из какой страны запросы выходят наружу.

    Главный вопрос при отказе по географии — действительно ли трафик идёт через
    VPN и в какой стране он выныривает. Догадаться об этом по ошибке нельзя.
    """
    session = requests.Session()
    apply_proxy(session, proxy_url, ignore_system_proxy)
    try:
        response = session.get(TRACE_URL, timeout=(timeout, timeout))
        values = dict(
            line.split("=", 1)
            for line in (response.text or "").splitlines()
            if "=" in line
        )
    except (requests.exceptions.RequestException, ValueError) as exc:
        log.debug("Адрес выхода определить не удалось: %s", str(exc)[:150])
        return ""
    finally:
        session.close()

    ip = values.get("ip", "")
    country = (values.get("loc") or "").upper()
    if not ip:
        return ""

    note = ""
    if country in _LIKELY_BLOCKED:
        note = " — ElevenLabs такие страны не обслуживает, смените страну в VPN"
    return f"{ip}, страна {country or 'не определена'}{note}"


@dataclass
class ProbeResult:
    """Что именно вернулось на один пробный запрос."""

    label: str
    url: str
    status: Optional[int] = None
    content_type: str = ""
    content_encoding: str = ""
    length: int = 0
    json_ok: bool = False
    snippet: str = ""
    error: str = ""
    elapsed: float = 0.0

    def line(self) -> str:
        if self.error:
            return f"{self.label}: не удалось — {self.error}"
        verdict = "JSON разобран" if self.json_ok else "ОТВЕТ НЕ JSON"
        encoding = f", сжатие {self.content_encoding}" if self.content_encoding else ""
        return (
            f"{self.label}: HTTP {self.status}, {verdict}, тип {self.content_type or 'не указан'}"
            f"{encoding}, {self.length} байт, {self.elapsed:.2f} с\n    начало: «{self.snippet}»"
        )


def decoder_support() -> str:
    """Какие способы сжатия умеет распаковать эта сборка.

    Если сервер сожмёт ответ способом, которого в сборке нет, тело придёт
    нечитаемым, а по ошибке разбора JSON это никак не опознать.
    """
    available = ["gzip", "deflate"]
    for name, label in (("brotli", "br"), ("brotlicffi", "br"), ("zstandard", "zstd")):
        try:
            __import__(name)
        except ImportError:
            continue
        if label not in available:
            available.append(label)
    return ", ".join(available)


def probe_connection(
    api_key: str = "",
    timeout: int = 30,
    base_url: str = BASE_URL,
    proxy_url: str = "",
    ignore_system_proxy: bool = False,
) -> List[ProbeResult]:
    """Постучаться в API и записать всё, что вернулось.

    Нужна, когда обычный запрос падает на разборе ответа: здесь видно и код,
    и заголовки, и настоящие байты тела, а не только сообщение JSON-разборщика.
    """
    key = (api_key or "").strip()
    if key:
        register_secret(key)

    checks = [("Список моделей без ключа", "/v1/models", False)]
    if key:
        checks.append(("Список моделей с ключом", "/v1/models", True))
        checks.append(("Сведения о подписке", "/v1/user/subscription", True))

    log.info("Проверка соединения. Поддерживаемое сжатие: %s", decoder_support())
    log.info("Путь в сеть: %s", describe_route(proxy_url, ignore_system_proxy))

    outbound = outbound_address(proxy_url=proxy_url, ignore_system_proxy=ignore_system_proxy)
    log.info("Выход в интернет: %s", outbound or "определить не удалось")

    session = requests.Session()
    apply_proxy(session, proxy_url, ignore_system_proxy)

    results: List[ProbeResult] = []
    for label, path, with_key in checks:
        url = f"{base_url.rstrip('/')}{path}"
        result = ProbeResult(label=label, url=url)
        headers = {"User-Agent": "elevenlabs-voiceover/1.0 (+desktop)", "Accept": "application/json"}
        if with_key:
            headers["xi-api-key"] = key

        started = time.monotonic()
        try:
            response = session.get(url, headers=headers, timeout=(15, timeout))
        except requests.exceptions.RequestException as exc:
            result.error = _explain_network_error(exc)
        else:
            body = response.content or b""
            result.status = response.status_code
            result.elapsed = time.monotonic() - started
            result.content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip()
            result.content_encoding = response.headers.get("Content-Encoding") or ""
            result.length = len(body)
            result.snippet = redact(
                body[:200].decode("utf-8", errors="replace").replace("\r", " ").replace("\n", " ").strip()
            )
            try:
                response.json()
                result.json_ok = True
            except ValueError:
                result.json_ok = False
                # Байты нужны целиком: по ним видно и сжатие, и подмену.
                log.warning("%s: тело не разобралось как JSON, первые байты: %r", label, body[:120])

        log.info("%s", result.line())
        results.append(result)

    session.close()
    return results


#: Признаки того, что соединение рвут снаружи, а не сервер отказал.
_BLOCKED_MARKERS = (
    "connection reset",
    "connection aborted",
    "connectionreseterror",
    "remotedisconnected",
    "eof occurred",
    "unexpected_eof",
    "record layer failure",
    "10054",
)


def _explain_network_error(exc: Exception) -> str:
    """Перевести сетевую ошибку в формулировку, по которой понятно, что делать.

    Порядок проверок важен. Когда не отвечает прокси, в тексте ошибки есть и
    слово timeout, и слово proxy: сообщить надо про прокси, потому что чинить
    нужно именно его.
    """
    text = str(exc)
    lowered = text.lower()

    if "proxy" in lowered or "socks" in lowered:
        return (
            "прокси из настроек не отвечает. Проверьте его адрес и порт, а если схема не "
            "указана — попробуйте socks5h://, многие прокси работают именно по нему. "
            f"Исходная ошибка: {text[:200]}"
        )
    if any(marker in lowered for marker in _BLOCKED_MARKERS):
        return (
            "соединение разорвано на полпути. Так выглядит фильтрация трафика: запрос до "
            "ElevenLabs не доходит, хотя интернет работает. Помогает VPN или прокси, "
            f"указанный в настройках. Исходная ошибка: {text[:200]}"
        )
    if "name or service not known" in lowered or "getaddrinfo" in lowered or "nodename" in lowered:
        return f"имя api.elevenlabs.io не разрешается в адрес — похоже на проблему с DNS. {text[:200]}"
    if "timed out" in lowered or "timeout" in lowered:
        return f"ответа не дождались за отведённое время. Исходная ошибка: {text[:200]}"
    return text[:300]


def _parse_error_body(response: requests.Response) -> Tuple[Optional[str], str, Any]:
    """Достать из тела ошибки её код и человекочитаемое сообщение."""
    try:
        payload = response.json()
    except ValueError:
        snippet = (response.text or "").strip()
        return None, snippet[:500], snippet[:2000]

    detail = payload.get("detail") if isinstance(payload, dict) else None

    if isinstance(detail, dict):
        status = detail.get("status")
        message = detail.get("message") or detail.get("detail") or ""
        return (str(status) if status else None), str(message), payload

    if isinstance(detail, list):
        # 422 от FastAPI: список ошибок валидации.
        parts = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(x) for x in (item.get("loc") or []))
                parts.append(f"{loc}: {item.get('msg')}" if loc else str(item.get("msg")))
        return None, "; ".join(p for p in parts if p)[:500], payload

    if isinstance(detail, str):
        return None, detail, payload

    if isinstance(payload, dict) and payload.get("message"):
        return payload.get("status"), str(payload["message"]), payload

    return None, (response.text or "")[:500], payload


def _retry_after_seconds(response: requests.Response) -> Optional[float]:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def verify_key(
    api_key: str,
    *,
    timeout: int = 60,
    cancel_event: Optional[threading.Event] = None,
    proxy_url: str = "",
    ignore_system_proxy: bool = False,
) -> Tuple[Subscription, List[ModelInfo]]:
    """Быстрая проверка ключа: подписка плюс список доступных моделей."""
    with ElevenLabsClient(
        api_key,
        timeout=timeout,
        max_retries=2,
        cancel_event=cancel_event,
        proxy_url=proxy_url,
        ignore_system_proxy=ignore_system_proxy,
    ) as client:
        subscription = client.get_subscription()
        try:
            models = client.list_models()
        except ElevenLabsError as exc:
            log.warning("Ключ рабочий, но список моделей получить не удалось: %s", exc)
            models = []
    return subscription, models


CancelCallback = Callable[[], bool]
