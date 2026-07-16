"""Точка входа: python -m autoshorts.cli <voice|montage|gui> [--cycles N]

Озвучка и монтаж — независимые команды, как и просил пользователь.
"""
from __future__ import annotations

import argparse
import sys

from .config import ConfigError, load_config
from .logging_setup import setup_logging


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", default="config.yaml", help="путь к config.yaml")
    p.add_argument("--cycles", type=int, default=1,
                   help="сколько прогонов сделать (озвучек или видео)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autoshorts",
                                     description="Автоозвучка и автомонтаж коротких видео")
    sub = parser.add_subparsers(dest="command", required=True)

    p_voice = sub.add_parser("voice", help="сгенерировать озвучку")
    _add_common(p_voice)

    p_montage = sub.add_parser("montage", help="собрать видео из готовой озвучки")
    _add_common(p_montage)
    p_montage.add_argument("--template", default="template.yaml",
                           help="путь к template.yaml")

    p_gui = sub.add_parser("gui", help="запустить десктопный интерфейс")
    p_gui.add_argument("--config", default="config.yaml")

    args = parser.parse_args(argv)

    try:
        if args.command == "gui":
            from .ui.app import run_gui
            return run_gui(args.config)

        cfg = load_config(args.config)
        setup_logging(cfg.logs_dir, cfg.logging.get("level", "INFO"),
                      int(cfg.logging.get("keep_files", 20)))

        if args.command == "voice":
            from .voice.pipeline import run_voice
            results = run_voice(cfg, cycles=args.cycles)
            print(f"Готово озвучек: {len(results)}")
            return 0

        if args.command == "montage":
            from .montage.orchestrator import run_montage
            produced = run_montage(cfg, cycles=args.cycles,
                                   template_path=args.template)
            print(f"Готово видео: {len(produced)}")
            for path in produced:
                print(f"  {path}")
            return 0
    except ConfigError as exc:
        print(f"Ошибка конфига: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Прервано пользователем.", file=sys.stderr)
        return 130

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
