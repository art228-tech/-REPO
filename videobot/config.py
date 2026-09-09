"""Настройки программы.

Токен бота хранится здесь же, в файле рядом с программой, и в git не попадает
никогда — папка с настройками закрыта `.gitignore`. Вводится он один раз в окне
программы и дальше живёт только на этом компьютере.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

FILE_NAME = "настройки.json"


@dataclass
class Settings:
    token: str = ""
    """Токен от @BotFather. Без него бот не запускается."""

    admin_id: int = 0
    """Кому доступна админка. Ноль — админом станет первый, кто нажмёт «Старт»."""

    registry_path: str = ""
    """Файл `данные роликов.jsonl` автомонтажа. Из него берутся данные ролика."""

    # Сколько действий в минуту разрешено одному человеку. Превысил — бот
    # молчит, а не отвечает ошибкой на каждое нажатие: иначе спамом можно
    # раскачать самого бота, отвечающего на спам.
    actions_per_minute: int = 20

    # Больше этого за раз не выдаётся, даже если доступно больше: сотня файлов
    # подряд — это и очередь на полчаса, и заваленный чат у человека.
    max_take_at_once: int = 25

    # Сторож нагрузки. Держится выше порога дольше, чем `cpu_grace_s`, — бот
    # встаёт на паузу и сам продолжает, когда отпустит.
    cpu_limit_percent: int = 85
    cpu_grace_s: int = 30

    # Через сколько часов после скачивания напомнить про просмотры. Ровно один
    # раз: человек мог не выложить ролик вовсе, и долбить его незачем.
    reminder_after_hours: int = 24

    notes: dict = field(default_factory=dict)
    """Место под будущие настройки, чтобы старый файл не ломался о новые поля."""


def path_for(folder: Path) -> Path:
    return folder / FILE_NAME


def load(folder: Path) -> Settings:
    """Читает настройки. Испорченный файл не должен мешать запуску окна."""
    target = path_for(folder)
    if not target.is_file():
        return Settings()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Settings()
    if not isinstance(raw, dict):
        return Settings()

    known = {item.name for item in fields(Settings)}
    return Settings(**{key: value for key, value in raw.items() if key in known})


def save(folder: Path, settings: Settings) -> None:
    target = path_for(folder)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def problems(settings: Settings) -> list[str]:
    """Что мешает запустить бота. Пустой список — можно запускать."""
    found: list[str] = []
    if not settings.token.strip():
        found.append("не введён токен бота — возьмите его у @BotFather")
    elif ":" not in settings.token:
        found.append("токен не похож на токен: в нём должно быть двоеточие")

    if not settings.registry_path.strip():
        found.append("не указан файл данных автомонтажа")
    elif not Path(settings.registry_path).is_file():
        found.append(f"файл данных не найден: {settings.registry_path}")

    return found
