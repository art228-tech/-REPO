"""Командная строка."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import batch, logging_setup, profile as profile_module, validate
from .config import Config, _default_drafts_dir
from .errors import PipelineError
from .logging_setup import get_logger

log = get_logger("cli")


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--drafts", type=Path, default=None,
                        help="папка черновиков CapCut (по умолчанию определяется автоматически)")
    parser.add_argument("--work", type=Path, default=None,
                        help="папка для журналов и использованных материалов")
    parser.add_argument("-v", "--verbose", action="store_true", help="подробный вывод в консоль")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="capcut-uniq",
        description="Пакетная сборка роликов CapCut по готовым шаблонам",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("gui", help="открыть окно программы")

    doctor = sub.add_parser("doctor", help="проверить окружение")
    _add_common(doctor)

    templates = sub.add_parser("templates", help="показать разбор шаблонов")
    templates.add_argument("names", nargs="*", help="имена папок шаблонов; без них — все проекты")
    _add_common(templates)

    check = sub.add_parser("check", help="проверить собранный черновик")
    check.add_argument("folder", type=Path)
    _add_common(check)

    diag = sub.add_parser("diagnose", help="сравнить субтитры ролика с шаблоном")
    diag.add_argument("template", help="папка шаблона")
    diag.add_argument("clone", help="папка собранного ролика")
    _add_common(diag)

    probe = sub.add_parser(
        "probe", help="положить в ролик субтитры шаблона без изменений (проба)")
    probe.add_argument("template", help="папка шаблона")
    probe.add_argument("clone", help="папка собранного ролика")
    _add_common(probe)

    run = sub.add_parser("run", help="собрать партию роликов")
    run.add_argument("--clips", type=Path, nargs="+", required=True,
                 help="папка с клипами; можно несколько, если короткие и длинные разложены отдельно")
    run.add_argument("--voice", type=Path, required=True, help="папка с озвучками")
    run.add_argument("--templates", nargs="+", required=True, help="шаблоны для ротации")
    run.add_argument("--count", type=int, default=1, help="сколько роликов собрать")
    run.add_argument("--seed", type=int, default=None, help="зерно случайности для повторяемости")
    run.add_argument("--fps", type=float, default=60.0)
    run.add_argument("--prefix", default="auto", help="префикс имён проектов")
    run.add_argument("--black-bg", type=int, default=0, metavar="N",
                     help="сколько роликов из каждых шести собрать без размытого фона (0-6)")
    run.add_argument("--three-frames", action="store_true",
                     help="из одного набора материалов три ролика: обычный и два со сдвигом кадра")
    run.add_argument("--random-names", action="store_true",
                     help="случайные имена проектов из русских и английских букв и цифр")
    run.add_argument("--name-length", type=int, default=10, help="длина случайного имени")
    run.add_argument("--no-subtitles", action="store_true", help="не собирать субтитры, а очистить дорожку")
    run.add_argument("--keep-inputs", action="store_true", help="не убирать использованные материалы")
    run.add_argument("--asr-model", default="small", help="модель распознавания: tiny, base, small, medium")
    _add_common(run)

    vary = sub.add_parser(
        "variants",
        help="собрать один ролик несколькими способами записи субтитров")
    vary.add_argument("--clips", type=Path, nargs="+", required=True)
    vary.add_argument("--voice", type=Path, required=True)
    vary.add_argument("--templates", nargs="+", required=True,
                      help="шаблон, на котором перебирать (достаточно одного)")
    vary.add_argument("--seed", type=int, default=None)
    vary.add_argument("--fps", type=float, default=60.0)
    vary.add_argument("--prefix", default="перебор")
    vary.add_argument("--keep-inputs", action="store_true", default=True,
                      help="по умолчанию материалы не расходуются")
    vary.add_argument("--asr-model", default="small")
    _add_common(vary)

    cut = sub.add_parser("split", help="нарезать длинное видео на клипы (на сборку не влияет)")
    cut.add_argument("source", type=Path, help="исходное видео")
    cut.add_argument("--out", type=Path, nargs="+", default=None,
                     help="куда складывать клипы: одна общая папка или по одной "
                          "на каждую длину из схемы, в том же порядке")
    cut.add_argument("--pattern", default="4 15",
                     help="длины фрагментов: одно число или чередование, например «4 15»")
    cut.add_argument("--trim-start", type=float, default=0.0, help="отрезать с начала, с")
    cut.add_argument("--trim-end", type=float, default=0.0, help="отрезать с конца, с")
    cut.add_argument("--keep-tail", action="store_true", help="оставить неполный остаток в конце")
    cut.add_argument("--copy", action="store_true",
                     help="не перекодировать: быстрее, но длина прыгает по опорным кадрам")
    cut.add_argument("--dry-run", action="store_true", help="только показать, что получится")
    _add_common(cut)

    return parser


def _config_from(args) -> Config:
    config = Config(
        clips_dir=getattr(args, "clips", None) or Path("."),
        voice_dir=getattr(args, "voice", Path(".")),
        templates=list(getattr(args, "templates", []) or []),
        count=getattr(args, "count", 1),
        seed=getattr(args, "seed", None),
        fps=getattr(args, "fps", 60.0),
        name_prefix=getattr(args, "prefix", "auto"),
        black_bg_of_six=getattr(args, "black_bg", 0),
        three_frames=getattr(args, "three_frames", False),
        random_names=getattr(args, "random_names", False),
        name_length=getattr(args, "name_length", 10),
        make_subtitles=not getattr(args, "no_subtitles", False),
        consume_inputs=not getattr(args, "keep_inputs", False),
        asr_model=getattr(args, "asr_model", "small"),
    )
    if getattr(args, "drafts", None):
        config.drafts_dir = args.drafts
    if getattr(args, "work", None):
        config.work_dir = args.work
    return config


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "gui":
        try:
            from .gui import main as gui_main
        except ImportError:
            print(
                "Не удалось открыть окно: в этой сборке Python нет tkinter.\n"
                "На Windows он входит в стандартный установщик — переустанови Python "
                "с python.org, отметив «tcl/tk and IDLE».\n"
                "Пока можно работать из консоли: python main.py run --help"
            )
            return 2
        return gui_main()

    config = _config_from(args)
    log_path = logging_setup.setup(config.log_dir, verbose=getattr(args, "verbose", False))

    try:
        if args.command == "doctor":
            return _doctor(config)
        if args.command == "templates":
            return _templates(config, args.names)
        if args.command == "check":
            return _check(args.folder)
        if args.command == "diagnose":
            return _diagnose(args, config)
        if args.command == "probe":
            return _probe(args, config)
        if args.command == "variants":
            return _variants(args, config)
        if args.command == "split":
            return _split(args)
        if args.command == "run":
            report = batch.run(config)
            print()
            print(report.summary())
            print(f"\nЖурнал: {log_path}")
            return 0 if report.failed == 0 else 1
    except PipelineError as exc:
        log.error("%s", exc)
        print(f"\nЖурнал: {log_path}")
        return 2
    return 0


def _doctor(config: Config) -> int:
    print("Проверка окружения")
    ok = True

    for tool in ("ffmpeg", "ffprobe"):
        found = shutil.which(tool)
        print(f"  {tool:8s} {'найден: ' + found if found else 'НЕ НАЙДЕН — поставь FFmpeg'}")
        ok = ok and bool(found)

    try:
        import faster_whisper  # noqa: F401
        print("  распознавание речи: faster-whisper установлен")
    except ImportError:
        print("  распознавание речи: НЕ УСТАНОВЛЕНО (pip install faster-whisper)")
        print("     без него не будет ни субтитров, ни точного стыка по предложению")
        ok = False

    drafts = config.drafts_dir
    print(f"  папка черновиков: {drafts}")
    if drafts.is_dir():
        projects = [p.name for p in sorted(drafts.iterdir()) if p.is_dir() and not p.name.startswith(".")]
        print(f"     проектов: {len(projects)}" + (f" — {', '.join(projects[:8])}" if projects else ""))
    else:
        print("     ПАПКА НЕ НАЙДЕНА — укажи её через --drafts")
        ok = False

    print("\nИтог: " + ("всё на месте" if ok else "есть чего не хватает, смотри выше"))
    return 0 if ok else 1


def _templates(config: Config, names: list[str]) -> int:
    drafts = config.drafts_dir
    if not drafts.is_dir():
        raise PipelineError(f"Папка черновиков не найдена: {drafts}")

    folders = [drafts / name for name in names] if names else [
        path for path in sorted(drafts.iterdir()) if path.is_dir() and not path.name.startswith(".")
    ]

    for folder in folders:
        try:
            print(profile_module.analyse(folder).describe())
        except PipelineError as exc:
            print(f"шаблон {folder.name}: не разобрать — {exc}")
        print()
    return 0


def _check(folder: Path) -> int:
    report = validate.check(folder)
    print(report.describe())
    return 0 if report.ok else 1


def _diagnose(args, config: Config) -> int:
    from . import diagnose

    def resolve(name: str) -> Path:
        folder = Path(name)
        return folder if folder.is_absolute() else config.drafts_dir / name

    report = diagnose.compare(resolve(args.template), resolve(args.clone))
    print(report.describe())
    path = diagnose.write_bundle(report, config.log_dir)
    print()
    print(f"Слепок для разбора: {path}")
    print("Пришли этот файл, если субтитров не видно.")
    return 0 if not report.problems else 1


def _variants(args, config: Config) -> int:
    """Собирает один ролик несколькими способами записи субтитров."""
    from . import batch, variants

    config.count = 1
    report = batch.run(config)
    made = next((o for o in report.outcomes if o.ok), None)
    if made is None or made.folder is None:
        print(report.summary())
        return 1
    if not made.cues:
        print("Реплик не получилось — перебирать нечего.")
        return 1

    template = next(iter(batch.discover_templates(config)))
    result = variants.build(config, made.folder, template.folder, made.cues)
    print()
    print(result.summary())
    return 0


def _probe(args, config: Config) -> int:
    from . import diagnose

    def resolve(name: str) -> Path:
        folder = Path(name)
        return folder if folder.is_absolute() else config.drafts_dir / name

    count = diagnose.restore_template_subtitles(resolve(args.template), resolve(args.clone))
    print(f"В ролик {args.clone} положены субтитры шаблона без изменений: {count} реплик.")
    print()
    print("Открой ролик в CapCut и посмотри на кадр.")
    print("  Видно субтитры  — дело в том, что собирает программа.")
    print("  Не видно        — собранные субтитры не при чём, CapCut не рисует")
    print("                    этот текстовый шаблон в таком проекте.")
    print()
    print("Прежний вариант сохранён рядом файлом draft_content.json.до_пробы")
    return 0


def _split(args) -> int:
    from . import ffmpeg, splitter

    pattern = splitter.parse_pattern(args.pattern)
    folders = args.out or [args.source.parent / "клипы"]
    targets = splitter.resolve_targets(pattern, folders)

    if args.dry_run:
        duration = ffmpeg.probe(args.source).duration_s
        pieces, tail = splitter.plan_cuts(
            duration, pattern, args.trim_start, args.trim_end, args.keep_tail
        )
        print(f"Видео: {duration:.2f}с, после обрезки {duration - args.trim_start - args.trim_end:.2f}с")
        print(f"Получится клипов: {len(pieces)}")
        for piece in pieces:
            print(f"  {piece.index:3d}  {piece.start_s:8.3f} → {piece.start_s + piece.duration_s:8.3f}"
                  f"  ({piece.duration_s:.3f}с)  → {targets[splitter.key(piece.requested_s)]}")
        if tail > 0:
            print(f"Остаток {tail:.2f}с будет отброшен")
        return 0

    def progress(done: int, total: int, message: str) -> None:
        print(f"  [{done}/{total}] {message}")

    report = splitter.split(
        args.source, folders, pattern, args.trim_start, args.trim_end,
        keep_tail=args.keep_tail, reencode=not args.copy, progress=progress,
    )
    print()
    print(report.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
