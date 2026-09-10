"""Отчёт о проблеме: один файл, который можно переслать.

Внутри окружение, настройки, последние ошибки, сводка по базе и журналы за
последние дни. По нему разбирают сбой, не спрашивая по десять раз «а что
написано в окне».

Токен вырезается отовсюду, а не только из настроек. Это не перестраховка:
Telegram кладёт токен прямо в адрес запроса, поэтому при ошибке сети он
попадает в журнал целиком, и отчёт с журналами унёс бы его с собой. Вырезается
и то, что просто похоже на токен, — на случай, если он лежит где-то ещё.
"""
from __future__ import annotations

import re
import zipfile
from datetime import datetime
from pathlib import Path

from . import logs

# Токен выглядит как «8123456789:AAH...» — число, двоеточие и длинный хвост.
TOKEN_SHAPE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}")
HIDDEN = "<токен вырезан>"

# Журналов берём немного: отчёт должен оставаться пересылаемым, а сбой почти
# всегда виден в последних днях.
KEEP_LOGS = 5


def scrub(text: str, token: str = "") -> str:
    """Убирает токен из текста — и известный, и любой похожий."""
    if token:
        text = text.replace(token, HIDDEN)
        head = token.split(":", 1)[0]
        if len(head) >= 6:
            text = text.replace(head, "<номер бота>")
    return TOKEN_SHAPE.sub(HIDDEN, text)


def summary(base) -> str:
    """Сводка по базе: сколько чего, без имён и переписки."""
    counts = base.counts()
    people = base.people()
    lines = [
        f"Роликов залито:      {counts['ready']}",
        f"  из них свободных:  {counts['free']}",
        f"В очереди на заливку:{counts['pending']}",
        f"Не залилось:         {counts['failed']}",
        f"Людей всего:         {len(people)}",
        f"  с доступом:        {sum(1 for row in people if row['has_access'])}",
        f"  админов:           {sum(1 for row in people if row['is_admin'])}",
        f"Роликов с просмотрами: {len(base.measured())}",
    ]
    return "\n".join(lines)


def build(folder: Path, settings, base=None) -> Path:
    """Собирает отчёт и возвращает путь к нему."""
    journals = folder / "данные" / "журналы"
    target = folder / "данные" / f"отчёт {datetime.now():%Y-%m-%d %H-%M}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)

    token = (settings.token or "").strip()

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("окружение.txt", scrub(logs.environment(), token))
        archive.writestr("настройки.txt", scrub(_settings(settings), token))

        errors = logs.errors()
        archive.writestr(
            "ошибки.txt",
            scrub("\n".join(errors), token) if errors else "Ошибок в этот запуск не было.")

        if base is not None:
            try:
                archive.writestr("база.txt", summary(base))
            except Exception as exc:  # noqa: BLE001 - отчёт важнее сводки
                archive.writestr("база.txt", f"Сводку собрать не вышло: {exc}")

        crash = journals / logs.CRASH_NAME
        if crash.is_file():
            archive.writestr(logs.CRASH_NAME, scrub(_read(crash), token))

        if journals.is_dir():
            files = sorted(journals.glob("*.log"), key=lambda item: item.name)
            for item in files[-KEEP_LOGS:]:
                archive.writestr(f"журналы/{item.name}", scrub(_read(item), token))

    return target


def _settings(settings) -> str:
    """Настройки в читаемом виде, с вырезанным токеном."""
    token = (settings.token or "").strip()
    if token:
        shown = "задан" if ":" in token else "задан, но не похож на токен"
    else:
        shown = "не задан"

    rows = [
        ("Токен", shown),
        ("ID админа в настройках",
         settings.admin_id or "не задан (первый нажавший «Старт»)"),
        ("Файл данных автомонтажа", settings.registry_path or "не указан"),
        ("Прокси", _proxy(settings.proxy_url)),
        ("Действий в минуту", settings.actions_per_minute),
        ("За раз выдаётся", settings.max_take_at_once),
        ("Порог процессора",
         f"{settings.cpu_limit_percent}% дольше {settings.cpu_grace_s} с"),
        ("Напоминание через", f"{settings.reminder_after_hours} ч"),
    ]
    width = max(len(name) for name, _ in rows)
    return "\n".join(f"{name.ljust(width)} : {value}" for name, value in rows)


def _proxy(raw: str) -> str:
    """Адрес прокси без логина и пароля — они там бывают, и это чужой секрет."""
    raw = (raw or "").strip()
    if not raw:
        return "не указан"
    if "@" in raw:
        return raw.split("@", 1)[1] + " (логин и пароль скрыты)"
    if raw.count(":") >= 3:
        host, port, *_ = raw.rsplit("://", 1)[-1].split(":")
        return f"{host}:{port} (логин и пароль скрыты)"
    return raw


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Файл не прочитался: {exc}"
