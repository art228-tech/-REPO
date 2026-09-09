"""Данные ролика по имени файла.

Автомонтаж на каждый собранный ролик дописывает строку в свой реестр
`данные роликов.jsonl`: фон, папка озвучки, музыка, длительность QR. Ролик вы
экспортируете из CapCut руками, и экспортированный файл несёт только имя —
всё остальное берётся отсюда.

Имя приходится искать не в лоб: CapCut и Windows дописывают к нему хвосты, а
файл могли переименовать вручную. Поэтому сначала точное совпадение, потом
поиск имени проекта внутри имени файла. Если нашлось несколько — ролик
отклоняется: подставить чужие данные хуже, чем не подставить никаких, потому
что ошибка всплывёт только испорченной статистикой.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# Хвосты, которые дописывают при повторном экспорте: «имя (1)», «имя(2)».
COPY_SUFFIX = re.compile(r"\s*\(\d+\)$")


@dataclass
class Match:
    file: Path
    name: str = ""
    data: dict | None = None
    problem: str = ""

    @property
    def ok(self) -> bool:
        return self.data is not None


def read(path: Path) -> dict[str, dict]:
    """Читает реестр автомонтажа в словарь «имя — данные».

    Битые строки пропускаются: запись могла оборваться на выключении, и терять
    из-за одной строки весь остальной реестр незачем. Повторное имя перекрывает
    прежнее — ролик пересобрали, и в папке черновиков лежит последняя сборка.
    """
    path = Path(path)
    if not path.is_file():
        return {}

    found: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("name"):
            found[str(record["name"])] = record
    return found


def clean(stem: str) -> str:
    """Убирает хвосты, которые дописываются при повторном экспорте."""
    cleaned = stem.strip()
    while True:
        shorter = COPY_SUFFIX.sub("", cleaned).strip()
        if shorter == cleaned:
            return cleaned
        cleaned = shorter


def match(file: Path, known: dict[str, dict]) -> Match:
    """Ищет данные ролика по имени файла."""
    file = Path(file)
    stem = clean(file.stem)

    if stem in known:
        return Match(file=file, name=stem, data=known[stem])

    # Файл могли переименовать, дописав что-то своё: «auto_0906_007 финал.mp4».
    # Имя проекта при этом осталось внутри — по нему и ищем.
    inside = [name for name in known if name and name in stem]
    if len(inside) == 1:
        name = inside[0]
        return Match(file=file, name=name, data=known[name])

    if len(inside) > 1:
        longest = max(inside, key=len)
        others = [name for name in inside if name != longest]
        if all(len(name) < len(longest) for name in others):
            return Match(file=file, name=longest, data=known[longest])
        return Match(
            file=file,
            problem=f"имени «{stem}» подходит несколько роликов: "
                    + ", ".join(sorted(inside)),
        )

    return Match(file=file, problem=f"нет данных для «{stem}»")


def match_all(files, known: dict[str, dict]) -> list[Match]:
    """Разбирает пачку файлов и ловит повторы внутри самой пачки."""
    results = [match(Path(item), known) for item in files]

    seen: dict[str, Match] = {}
    for item in results:
        if not item.ok:
            continue
        if item.name in seen:
            item.data = None
            item.problem = (
                f"этот ролик уже есть в списке — «{seen[item.name].file.name}»"
            )
        else:
            seen[item.name] = item
    return results
