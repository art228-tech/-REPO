"""Точка входа.

Без аргументов открывается окно. Любой аргумент, кроме --gui, переводит
программу в консольный режим.
"""

from __future__ import annotations

import sys


def main() -> int:
    argv = sys.argv[1:]

    if not argv or argv == ["--gui"]:
        from .gui import main as gui_main

        return gui_main()

    from .cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
