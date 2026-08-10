"""Запуск без окна — для проверки настроек и работы по расписанию."""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path
from typing import List, Optional

from .api_client import decoder_support, probe_connection, safe_proxy_summary, verify_key
from .config import MODE_ALL_VOICES, MODE_ROUND_ROBIN, Settings
from .diagnostics import build_report
from .errors import ElevenLabsError
from .logging_setup import add_gui_handler, get_logger, setup_logging
from .runner import PreflightError, Runner, estimate_plan
from .state import StateStore

log = get_logger("cli")


def say(text: str = "", *, error: bool = False) -> None:
    """Печать, безопасная в собранном exe.

    Сборка идёт с ключом --windowed, и тогда стандартные потоки могут
    отсутствовать: обычный print в такой ситуации падает.
    """
    stream = sys.stderr if error else sys.stdout
    if stream is None:
        return
    try:
        stream.write(text + "\n")
        stream.flush()
    except (OSError, ValueError):
        pass


def _print_progress(fraction: float, message: str) -> None:
    if sys.stdout is None:
        return
    try:
        sys.stdout.write(f"\r[{fraction * 100:5.1f}%] {message[:100]:<100}")
        sys.stdout.flush()
    except (OSError, ValueError):
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="elevenlabs-voiceover",
        description="Пакетная озвучка текстов через API ElevenLabs.",
    )
    parser.add_argument("--gui", action="store_true", help="открыть окно программы")
    parser.add_argument("--api-key", help="API-ключ (иначе берётся из настроек или ELEVENLABS_API_KEY)")
    parser.add_argument("--prompts", help="папка с промптами голосов")
    parser.add_argument("--texts", help="папка с текстами")
    parser.add_argument("--output", help="папка для результатов")
    parser.add_argument("--model", help="модель озвучки, например eleven_flash_v2_5")
    parser.add_argument("--voices", type=int, help="сколько голосов создать")
    parser.add_argument(
        "--mode",
        choices=[MODE_ROUND_ROBIN, MODE_ALL_VOICES],
        help="round_robin — голоса по кругу, all_voices — каждый текст всеми голосами",
    )
    parser.add_argument("--reserve", type=int, help="сколько кредитов не тратить")
    parser.add_argument("--chunk", type=int, help="символов в одном куске")
    parser.add_argument("--recreate-voices", action="store_true", help="создать голоса заново")
    parser.add_argument("--check", action="store_true", help="проверить ключ и выйти")
    parser.add_argument(
        "--diagnose", action="store_true",
        help="показать, что именно возвращает API: код, заголовки и начало тела",
    )
    parser.add_argument("--estimate", action="store_true", help="показать оценку объёма и выйти")
    parser.add_argument("--report", action="store_true", help="собрать диагностический отчёт и выйти")
    parser.add_argument("--save", action="store_true", help="сохранить переданные параметры в настройки")
    return parser


def apply_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    if args.api_key:
        settings.api_key = args.api_key
    if args.prompts:
        settings.prompts_dir = str(Path(args.prompts).expanduser())
    if args.texts:
        settings.texts_dir = str(Path(args.texts).expanduser())
    if args.output:
        settings.output_dir = str(Path(args.output).expanduser())
    if args.model:
        settings.model_id = args.model
    if args.voices:
        settings.max_voices = args.voices
    if args.mode:
        settings.voice_mode = args.mode
    if args.reserve is not None:
        settings.reserve_credits = args.reserve
    if args.chunk:
        settings.chunk_target_chars = args.chunk
    if args.recreate_voices:
        settings.recreate_voices = True
    settings.normalize()
    return settings


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    setup_logging()
    add_gui_handler(lambda line, level: say(line))

    settings = apply_overrides(Settings.load(), args)

    if args.save:
        settings.save()
        say("Настройки сохранены.")

    if args.report:
        say(f"Отчёт: {build_report(settings)}")
        return 0

    if args.estimate:
        for key, value in estimate_plan(settings).items():
            say(f"{key}: {value}")
        return 0

    if args.diagnose:
        say(f"Сжатие, доступное программе: {decoder_support()}")
        say(f"Прокси: {safe_proxy_summary() or 'не настроен'}")
        say("")
        broken = 0
        for result in probe_connection(settings.resolved_api_key(), timeout=settings.request_timeout):
            say(result.line())
            if result.error or not result.json_ok:
                broken += 1
        say("")
        say("Соединение в порядке." if not broken else f"Запросов с неожиданным ответом: {broken}")
        return 0 if not broken else 1

    if args.check:
        try:
            subscription, models = verify_key(settings.resolved_api_key())
        except ElevenLabsError as exc:
            say(f"Ключ не принят: {exc}", error=True)
            return 2
        say(subscription.summary())
        say("Доступные модели озвучки:")
        for model in models:
            if model.can_do_text_to_speech:
                say(f"  {model.model_id:<28} {model.cost_multiplier:g} кред./символ, "
                    f"до {model.max_chars_per_request} символов")
        return 0

    state = StateStore()
    cancel = threading.Event()
    runner = Runner(settings, state, cancel_event=cancel, on_progress=_print_progress)

    try:
        stats = runner.run()
    except PreflightError as exc:
        say(f"\nНевозможно запустить: {exc}", error=True)
        return 2
    except KeyboardInterrupt:
        cancel.set()
        say("\nОстановлено.")
        return 130
    finally:
        state.close()

    say()
    for key, value in stats.as_dict().items():
        say(f"{key}: {value}")
    return 0 if not stats.texts_failed else 1
