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

import requests

from .errors import (
    AuthError,
    Cancelled,
    ElevenLabsError,
    NetworkError,
    QuotaExceeded,
    RateLimited,
    ScopeError,
    ServerError,
    ValidationFailed,
    VoiceLimitReached,
)
from .logging_setup import get_logger, register_secret

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
            except requests.exceptions.Timeout as exc:
                error: ElevenLabsError = NetworkError(f"Таймаут запроса: {exc}", endpoint=path)
            except requests.exceptions.ConnectionError as exc:
                error = NetworkError(f"Нет соединения с API: {exc}", endpoint=path)
            except requests.exceptions.RequestException as exc:
                error = NetworkError(f"Ошибка запроса: {exc}", endpoint=path)
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
                    except ValueError as exc:
                        raise ElevenLabsError(
                            f"API вернул не-JSON ответ: {exc}",
                            status_code=response.status_code,
                            endpoint=path,
                        ) from exc
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
) -> Tuple[Subscription, List[ModelInfo]]:
    """Быстрая проверка ключа: подписка плюс список доступных моделей."""
    with ElevenLabsClient(api_key, timeout=timeout, max_retries=2, cancel_event=cancel_event) as client:
        subscription = client.get_subscription()
        try:
            models = client.list_models()
        except ElevenLabsError as exc:
            log.warning("Ключ рабочий, но список моделей получить не удалось: %s", exc)
            models = []
    return subscription, models


CancelCallback = Callable[[], bool]
