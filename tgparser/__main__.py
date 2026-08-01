"""Точка входа: `python -m tgparser [run|genkey|check]`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from tgparser.config import get_settings


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Telethon на INFO очень болтлив.
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


def cmd_genkey() -> int:
    from tgparser.crypto import generate_key

    print(generate_key())
    print(
        "\nПоложите значение в SESSION_ENCRYPTION_KEY в .env.\n"
        "Потеряете ключ — сохранённая сессия аккаунта станет нечитаемой "
        "и аккаунт придётся подключать заново.",
        file=sys.stderr,
    )
    return 0


def cmd_check() -> int:
    settings = get_settings()
    missing = settings.missing_required()
    if missing:
        print("Не заданы: " + ", ".join(missing))
        return 1
    print("Конфигурация заполнена.")
    print(f"База: {settings.db_path}")
    print(f"Выгрузки: {settings.export_dir}")
    print(f"Владелец: {settings.owner_id}")
    return 0


def cmd_run() -> int:
    from tgparser.bot.app import run

    settings = get_settings()
    _configure_logging(settings.log_level)
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        print("Остановлено.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tgparser", description="Парсер чатов Telegram")
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=("run", "genkey", "check"),
        help="run — запустить бота, genkey — сгенерировать ключ шифрования, "
        "check — проверить конфигурацию",
    )
    args = parser.parse_args(argv)

    if args.command == "genkey":
        return cmd_genkey()
    if args.command == "check":
        return cmd_check()
    return cmd_run()


if __name__ == "__main__":
    raise SystemExit(main())
