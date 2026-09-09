"""Реестр собранных роликов: те же данные, но в машинном виде.

Журнал партии пишется для чтения глазами, и разбирать его программой нельзя:
любая правка формулировки тихо ломает разбор, а заметно это становится уже по
испорченной статистике. Поэтому рядом с журналом кладётся реестр — по строке на
ролик, всегда одни и те же поля.

Читает его загрузчик роликов в телеграм-бота: пользователь экспортирует ролик из
CapCut руками, а данные к нему подтягиваются отсюда по имени.

Ключ — имя проекта, оно же имя, которое CapCut предложит при экспорте. Строка
дописывается в конец файла, поэтому оборванная посередине запись портит только
себя, а не весь реестр.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .logging_setup import get_logger

log = get_logger("registry")

FILE_NAME = "данные роликов.jsonl"


def path_for(work_dir: Path) -> Path:
    return work_dir / FILE_NAME


def entry(name: str, plan, duration_us: int, template: str) -> dict:
    """Собирает запись о ролике из плана, по которому он собран."""
    return {
        "name": name,
        "template": template,
        "duration_s": round(duration_us / 1_000_000, 3),
        "background": "black" if plan.black_background else "blur",
        # Папку озвучки пользователь выбирает сам, и по ней он же потом читает
        # статистику. Поэтому имя папки идёт как есть, без перевода в свои
        # обозначения: появится третья папка — она сама себя и назовёт.
        "voice_folder": plan.voice_path.parent.name,
        "music": plan.music is not None,
        "qr_s": round(plan.qr.duration_us / 1_000_000, 3) if plan.qr else 0.0,
        "built_at": datetime.now().isoformat(timespec="seconds"),
    }


def append(work_dir: Path, record: dict) -> None:
    """Дописывает запись в реестр. Сбой записи не должен ронять сборку."""
    target = path_for(work_dir)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as exc:
        log.warning("Не удалось записать ролик %s в реестр: %s", record.get("name"), exc)


def read(work_dir: Path) -> dict[str, dict]:
    """Читает реестр в словарь «имя — данные».

    Битые строки пропускаются: реестр мог оборваться на середине записи, и
    терять из-за этого весь остальной разбор незачем.

    Одно имя может встретиться дважды, если ролик пересобирали. Побеждает
    последняя запись: в папке черновиков лежит именно она.
    """
    target = path_for(work_dir)
    if not target.is_file():
        return {}

    found: dict[str, dict] = {}
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            log.warning("Реестр, строка %d: не разобралась, пропускаю", number)
            continue
        name = record.get("name")
        if name:
            found[str(name)] = record
    return found
