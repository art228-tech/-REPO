"""Точка входа: окно программы, проверка окружения, запуск без окна."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config as config_module
from . import logs


def _folder() -> Path:
    """Папка программы: рядом с ней лежат настройки, база и журналы."""
    return Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="videobot",
        description="Раздача собранных роликов через телеграм-бота")
    parser.add_argument("command", nargs="?", default="gui",
                        choices=["gui", "doctor", "headless"],
                        help="gui — окно программы, doctor — проверка, "
                             "headless — бот без окна")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="подробный журнал")
    args = parser.parse_args(argv)

    folder = _folder()
    journal = logs.setup(folder / "данные" / "журналы", verbose=args.verbose)

    if args.command == "doctor":
        return _doctor(folder, journal)
    if args.command == "headless":
        return _headless(folder)

    try:
        from . import gui
    except ImportError as exc:
        print("Окно не открылось: не найден tkinter.")
        print(f"Причина: {exc}")
        print("На Windows он ставится вместе с Python — переустановите Python "
              "с python.org, отметив «tcl/tk and IDLE».")
        return 2

    gui.run(folder)
    return 0


def _doctor(folder: Path, journal: Path) -> int:
    print(f"Папка программы: {folder}")
    print(f"Журнал: {journal}")

    ok = True
    for name in ("aiogram", "psutil"):
        try:
            __import__(name)
            print(f"  {name}: есть")
        except ImportError:
            print(f"  {name}: НЕТ — выполните: pip install -r requirements.txt")
            ok = False

    try:
        import tkinter  # noqa: F401
        print("  tkinter: есть")
    except ImportError:
        print("  tkinter: НЕТ — окно не откроется, но бот работает и без него")

    settings = config_module.load(folder)
    troubles = config_module.problems(settings)
    if troubles:
        print("Настройки:")
        for item in troubles:
            print(f"  • {item}")
        ok = False
    else:
        print("Настройки: в порядке")

    return 0 if ok else 1


def _headless(folder: Path) -> int:
    """Бот без окна — на случай, если нужен автозапуск в фоне."""
    import asyncio

    from .db import Base
    from .guard import Guard
    from .tg.app import serve

    settings = config_module.load(folder)
    troubles = config_module.problems(settings)
    if troubles:
        for item in troubles:
            print(f"• {item}")
        return 1

    base = Base(folder / "данные" / "bot.sqlite3")
    guard = Guard(settings.cpu_limit_percent, settings.cpu_grace_s)

    async def go() -> None:
        await serve(base, settings, guard, asyncio.Event())

    try:
        asyncio.run(go())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
