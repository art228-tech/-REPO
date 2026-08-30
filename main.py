"""Точка входа. Без аргументов открывает окно, с аргументами работает как консольная утилита."""
from __future__ import annotations

import sys

from capcut_uniq.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["gui"]))
