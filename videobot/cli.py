"""Точка входа: окно программы, проверка окружения, запуск без окна.

Всё завёрнуто в перехват: программа может упасть до того, как появится окно, и
тогда показать причину больше негде. Она пишется в `данные/журналы/сбой.txt` и
выводится на экран — а `run.bat` держит консоль открытой, чтобы её было видно.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from . import config as config_module
from . import logs


def _folder() -> Path:
    """Папка программы: рядом с ней лежат настройки, база и журналы."""
    return Path(__file__).resolve().parent.parent


def _journals(folder: Path) -> Path:
    return folder / "данные" / "журналы"


def _say(text: str) -> None:
    """Печатает, если есть куда.

    Под pythonw и в некоторых службах stdout отсутствует, и обычный print там
    падает с AttributeError — то есть сообщение об ошибке само становится
    ошибкой, и причина теряется окончательно.
    """
    try:
        if sys.stdout is not None:
            print(text)
    except Exception:  # noqa: BLE001 - вывод сообщения не стоит падения
        pass


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
    try:
        return _work(folder, args)
    except Exception as error:  # noqa: BLE001 - причина обязана дойти до человека
        where = logs.crash(_journals(folder), error)
        _say("")
        _say("=" * 60)
        _say("Программа не смогла запуститься. Причина ниже.")
        _say("=" * 60)
        _say("".join(traceback.format_exception(
            type(error), error, error.__traceback__)))
        _say(f"То же самое записано в файл: {where}")
        _say("Пришлите этот файл — по нему видно, что случилось.")
        return 1


def _work(folder: Path, args) -> int:
    journal = logs.setup(_journals(folder), verbose=args.verbose)

    # Прошлый сбой убираем: иначе он попадёт в отчёт и уведёт разбор в сторону,
    # хотя проблема давно другая.
    old = _journals(folder) / logs.CRASH_NAME
    if old.is_file():
        old.unlink(missing_ok=True)

    if args.command == "doctor":
        return _doctor(folder, journal)
    if args.command == "headless":
        return _headless(folder)

    try:
        from . import gui
    except ImportError as exc:
        _say("Окно не открылось: не найден tkinter.")
        _say(f"Причина: {exc}")
        _say("На Windows он ставится вместе с Python — переустановите Python "
             "с python.org, отметив «tcl/tk and IDLE».")
        logs.get_logger("запуск").error("tkinter не найден: %s", exc)
        return 2

    gui.run(folder)
    return 0


def _doctor(folder: Path, journal: Path) -> int:
    _say(f"Папка программы: {folder}")
    _say(f"Журнал: {journal}")

    ok = True
    for name in ("aiogram", "psutil"):
        try:
            __import__(name)
            _say(f"  {name}: есть")
        except ImportError:
            _say(f"  {name}: НЕТ — выполните: pip install -r requirements.txt")
            ok = False

    try:
        import tkinter  # noqa: F401
        _say("  tkinter: есть")
    except ImportError as exc:
        _say(f"  tkinter: НЕТ ({exc}) — окно не откроется, но бот работает и без него")
        ok = False

    settings = config_module.load(folder)
    troubles = config_module.problems(settings)
    if troubles:
        _say("Настройки:")
        for item in troubles:
            _say(f"  • {item}")
        ok = False
    else:
        _say("Настройки: в порядке")

    _say("")
    _say(logs.environment())
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
            _say(f"• {item}")
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
