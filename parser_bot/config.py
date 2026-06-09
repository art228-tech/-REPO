"""Конфигурация приложения.

Значения берутся из переменных окружения (.env). Токен бота и id админа
имеют значения по умолчанию из задания, но их лучше переопределять через .env.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _str(name: str, default: str) -> str:
    """Возвращает default, если переменная не задана ИЛИ пустая."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip()


@dataclass
class Config:
    # Бот управления
    bot_token: str = _str("BOT_TOKEN", "8543204345:AAE_h5gLkubItmyiF0lX31LlYBb8OWFgQhk")
    admin_id: int = _int("ADMIN_ID", 8266999073)

    # Telegram API (для входа в аккаунт через Telethon).
    # По умолчанию — личные ключи (проверены, рабочие). Можно переопределить в .env.
    api_id: int = _int("API_ID", 33641898)
    api_hash: str = _str("API_HASH", "64869358174f0ce375d887edc013cec6")

    # Параметры парсинга (значения по умолчанию; можно менять из бота — см. settings)
    min_members: int = _int("MIN_MEMBERS", 1000)
    min_messages_per_day: int = _int("MIN_MESSAGES_PER_DAY", 50)
    check_interval: int = _int("CHECK_INTERVAL", 25)
    probe_wait: int = _int("PROBE_WAIT", 12)
    # Сколько последних сообщений берём для оценки активности (сообщений/сутки)
    activity_sample: int = _int("ACTIVITY_SAMPLE", 60)

    db_path: Path = field(default_factory=lambda: Path(_str("DB_PATH", "data/parser.db")))

    # Ключевые слова для эвристического детекта.
    captcha_keywords: tuple[str, ...] = (
        "капч", "captcha", "не робот", "не бот", "докажите", "подтвердите что вы",
        "verify you", "решите пример", "проверка", "i am not a robot", "press the button",
        "нажмите кнопку", "введите код", "подтверди", "human", "antispam", "анти-спам",
        "antibot", "анти-бот",
    )
    op_keywords: tuple[str, ...] = (
        "подпис", "обязательная подписка", "оп ", "subscribe", "subscription",
        "join the", "вступите", "подпишись", "подпишитесь", "must join",
        "чтобы писать", "чтобы отправлять", "доступ к чату", "join these",
        "подписаться на", "required channels", "обязательн",
    )

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.bot_token or ":" not in self.bot_token:
            problems.append("BOT_TOKEN не задан или некорректен")
        if not self.admin_id:
            problems.append("ADMIN_ID не задан")
        if not self.api_id or not self.api_hash:
            problems.append(
                "API_ID/API_HASH не заданы — вход в аккаунт через Telethon работать не будет. "
                "Получите их на https://my.telegram.org"
            )
        return problems


config = Config()
