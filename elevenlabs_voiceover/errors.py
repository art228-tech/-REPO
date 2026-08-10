"""Типы ошибок ElevenLabs.

Разделение на классы нужно оркестратору: одни ошибки имеет смысл повторять,
другие означают немедленную остановку, третьи — пропуск конкретного задания.
"""

from __future__ import annotations

from typing import Any, Optional


class ElevenLabsError(Exception):
    """Базовая ошибка обращения к API."""

    #: повторять ли запрос автоматически
    retryable = False
    #: останавливать ли всю работу
    fatal = False

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        payload: Any = None,
        endpoint: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload
        self.endpoint = endpoint

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code is not None:
            parts.append(f"HTTP {self.status_code}")
        if self.endpoint:
            parts.append(self.endpoint)
        return " | ".join(parts)


class NetworkError(ElevenLabsError):
    """Сеть недоступна, таймаут, обрыв соединения."""

    retryable = True


class ProxyFailure(ElevenLabsError):
    """Прокси из настроек не отвечает.

    Повторять бессмысленно: это не помеха на линии, а неверная настройка, и
    каждая попытка стоит человеку ещё одного таймаута ожидания впустую.
    """

    retryable = False


class RateLimited(ElevenLabsError):
    """429: слишком много запросов."""

    retryable = True

    def __init__(self, message: str, *, retry_after: Optional[float] = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class ServerError(ElevenLabsError):
    """5xx на стороне ElevenLabs."""

    retryable = True


class AuthError(ElevenLabsError):
    """Ключ отсутствует, неверен или отозван."""

    fatal = True


class ScopeError(ElevenLabsError):
    """Ключу не хватает прав, либо запрос пришёл с неразрешённого IP.

    Самая частая причина: при создании ключа не отмечены нужные разрешения.
    """

    fatal = True


class QuotaExceeded(ElevenLabsError):
    """Кредиты на аккаунте закончились."""

    fatal = True


class InvalidResponse(ElevenLabsError):
    """Ответ пришёл с кодом успеха, но это не то, что отдаёт API.

    Почти всегда означает, что соединение читает кто-то посередине: антивирус
    с проверкой HTTPS, корпоративный прокси, VPN или страница-заглушка
    провайдера. Повторить стоит: перехват бывает и разовым.
    """

    retryable = True


class ValidationFailed(ElevenLabsError):
    """422: запрос не прошёл валидацию. Повтор не поможет."""


class VoiceLimitReached(ElevenLabsError):
    """Свободных слотов для голосов не осталось."""

    fatal = True


class Cancelled(Exception):
    """Пользователь остановил работу."""
