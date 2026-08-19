"""Логирование с гарантированной вырезкой API-ключа.

Логи предназначены для отправки на разбор, поэтому ключ не должен попасть в них
ни при каких обстоятельствах. Вырезка сделана на уровне форматтера, а не
фильтра: так она покрывает и сообщение, и аргументы, и текст трейсбека.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import threading
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from .paths import logs_dir

LOGGER_NAME = "ell"

#: Ключи ElevenLabs имеют вид sk_<hex>. Ловим и их, и обобщённый xi-api-key.
_KEY_PATTERNS: List[re.Pattern] = [
    re.compile(r"sk_[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)(xi-api-key\s*[:=]\s*)([^\s,'\"}\]]+)"),
    re.compile(r"(?i)(api[_-]?key\"?\s*[:=]\s*\"?)([A-Za-z0-9_\-]{8,})"),
]

_MASK = "***REDACTED***"

_secrets_lock = threading.Lock()
_registered_secrets: List[str] = []


def register_secret(value: Optional[str]) -> None:
    """Добавить конкретную строку в список вырезаемых.

    Вызывается при вводе ключа: даже если формат ключа изменится и перестанет
    подходить под регулярку, точное значение всё равно будет вырезано.
    """
    if not value or len(value) < 8:
        return
    with _secrets_lock:
        if value not in _registered_secrets:
            _registered_secrets.append(value)


def forget_secrets() -> None:
    with _secrets_lock:
        _registered_secrets.clear()


def redact(text: str) -> str:
    """Вырезать из строки всё, что похоже на секрет."""
    if not text:
        return text

    with _secrets_lock:
        secrets = list(_registered_secrets)
    for secret in secrets:
        if secret in text:
            text = text.replace(secret, _MASK)

    for pattern in _KEY_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(lambda m: f"{m.group(1)}{_MASK}", text)
        else:
            text = pattern.sub(_MASK, text)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class CallbackHandler(logging.Handler):
    """Отдаёт готовые строки в GUI.

    Ошибки самого GUI-приёмника подавляются: падение окна логов не должно
    ронять рабочий поток.
    """

    def __init__(self, callback: Callable[[str, str], None], level: int = logging.INFO) -> None:
        super().__init__(level)
        self._callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._callback(self.format(record), record.levelname)
        except Exception:  # noqa: BLE001 - GUI не должен ломать работу
            pass


_FILE_FMT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_GUI_FMT = "%(asctime)s  %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging(verbose: bool = True) -> logging.Logger:
    """Настроить корневой логгер приложения. Повторные вызовы безопасны."""
    global _configured
    logger = logging.getLogger(LOGGER_NAME)
    if _configured:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    log_file = logs_dir() / "app.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=4 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler.setFormatter(RedactingFormatter(_FILE_FMT, datefmt=_DATE_FMT))
    logger.addHandler(file_handler)

    _configured = True
    logger.debug("Логирование инициализировано, файл: %s", log_file)
    return logger


def add_gui_handler(callback: Callable[[str, str], None], level: int = logging.INFO) -> CallbackHandler:
    handler = CallbackHandler(callback, level=level)
    handler.setFormatter(RedactingFormatter(_GUI_FMT, datefmt="%H:%M:%S"))
    logging.getLogger(LOGGER_NAME).addHandler(handler)
    return handler


def remove_handler(handler: logging.Handler) -> None:
    logging.getLogger(LOGGER_NAME).removeHandler(handler)


def get_logger(suffix: str = "") -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{suffix}" if suffix else LOGGER_NAME)


def log_files() -> Iterable[Path]:
    directory = logs_dir()
    return sorted(directory.glob("app.log*"))
