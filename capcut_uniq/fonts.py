"""Поиск настоящего файла шрифта для субтитра.

Шаблоны сделаны на телефоне, поэтому шрифт в них записан телефонным путём вроде
``/data/user/0/com.lemon.lvoverseas/files/resources/effect/artists/<номер>/<хэш>/font.ttf``.
На ноутбуке такой папки нет. Пока субтитр шёл через текстовый шаблон, это не
мешало: шрифт брался из ресурсов самого текстового шаблона, а там путь записан
настоящий, до кэша CapCut. Как только субтитр стал обычным текстом, эта ссылка
ушла вместе с текстовым шаблоном — и CapCut начал подставлять свой шрифт, один и
тот же в любом проекте.

Здесь шрифт разыскивается по номеру ресурса в кэше CapCut. Корень кэша не
угадывается, а берётся из путей, записанных в самом черновике: их CapCut писал
сам, значит они верные для этой машины.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .logging_setup import get_logger

log = get_logger("fonts")

SUFFIXES = (".ttf", ".otf", ".ttc")
CACHE_MARK = "/cache/effect/"


def cache_roots(draft, drafts_dir: Path | None = None,
                recorded: tuple[str, ...] = ()) -> list[Path]:
    """Возможные корни кэша эффектов CapCut, по записям самого черновика.

    Корень не угадывается: берутся пути, которые CapCut записал сам, значит для
    этой машины они верные.
    """
    found: list[Path] = []

    def remember(path: Path) -> None:
        if path.is_dir() and path not in found:
            found.append(path)

    def from_path(value: str) -> None:
        cleaned = (value or "").replace("\\", "/")
        mark = cleaned.lower().find(CACHE_MARK)
        if mark > 0:
            remember(Path(cleaned[:mark + len(CACHE_MARK)]))

    for value in recorded:
        from_path(value)

    for material in draft.materials.get("text_templates") or []:
        for resource in material.get("resources") or []:
            from_path(resource.get("path") or "")

    # Черновики лежат в «User Data/Projects/...», кэш — в «User Data/Cache/effect».
    if drafts_dir is not None:
        for parent in Path(drafts_dir).resolve().parents:
            candidate = parent / "Cache" / "effect"
            if candidate.is_dir():
                remember(candidate)
                break

    return found


def find(resource_id: str, roots: list[Path]) -> Path | None:
    """Файл шрифта по номеру ресурса. Ищется только внутри его собственной папки."""
    if not resource_id:
        return None
    for root in roots:
        folder = root / resource_id
        if not folder.is_dir():
            continue
        for item in sorted(folder.rglob("*")):
            if item.is_file() and item.suffix.lower() in SUFFIXES:
                return item
    return None


@dataclass
class Choice:
    """Что вышло с поиском шрифта — и главное, свой он или запасной."""

    path: str = ""
    source: str = "нет"
    """«записанный» — путь из шаблона и так открывается; «свой» — нашли в кэше
    тот шрифт, который просит шаблон; «запасной» — свой не нашёлся, взяли шрифт
    из ресурсов текстового шаблона; «нет» — не нашлось ничего."""

    asked: list[str] = field(default_factory=list)
    title: str = ""

    @property
    def own(self) -> bool:
        return self.source in ("записанный", "свой")

    def describe(self) -> str:
        name = self.title or (Path(self.path).name if self.path else "не указан")
        if self.source == "записанный":
            return f"шрифт {name}: путь из шаблона открывается, оставляю как есть"
        if self.source == "свой":
            return f"шрифт {name}: свой шрифт шаблона, найден в кэше CapCut"
        if self.source == "запасной":
            return (f"шрифт {Path(self.path).name}: ЗАПАСНОЙ из текстового шаблона — "
                    f"свой ({', '.join(self.asked) or 'не указан'}) на диске не найден, "
                    f"поэтому у таких шаблонов шрифт будет одинаковый")
        return (f"шрифт не найден совсем — CapCut подставит свой, одинаковый везде. "
                f"Просит: {', '.join(self.asked) or 'не указан'}")


def titles(material: dict) -> dict[str, str]:
    """Названия шрифтов по номеру ресурса — чтобы в журнале были имена, а не цифры."""
    found: dict[str, str] = {}
    for entry in material.get("fonts") or []:
        number = entry.get("resource_id") or entry.get("effect_id") or ""
        if number and entry.get("title"):
            found[number] = entry["title"]
    return found


def wanted(material: dict) -> list[str]:
    """Номера ресурсов шрифтов, которые просит текстовый материал."""
    numbers: list[str] = []
    for entry in material.get("fonts") or []:
        number = entry.get("resource_id") or entry.get("effect_id") or ""
        if number and number not in numbers:
            numbers.append(number)

    try:
        body = json.loads(material.get("content") or "{}")
    except ValueError:
        body = {}
    for style in body.get("styles") or []:
        number = (style.get("font") or {}).get("id") or ""
        if number and number not in numbers:
            numbers.append(number)
    return numbers


def usable(path: str) -> bool:
    """Ведёт ли записанный путь к существующему файлу на этой машине."""
    if not path:
        return False
    return Path(path.replace("\\", "/")).is_file()


def resolve(material: dict, roots: list[Path], spare: str = "") -> Choice:
    """Какой шрифт подставить текстовому материалу.

    Порядок такой: если записанный путь и так открывается — ничего не меняем.
    Иначе ищем в кэше тот шрифт, который материал просит, — так у каждого шаблона
    остаётся свой. Если не нашёлся, берём запасной: шрифт из ресурсов текстового
    шаблона, тот самый, которым шаблон и рисовался. Он общий для всех шаблонов,
    поэтому такой исход отмечается отдельно.
    """
    asked = wanted(material)
    names = titles(material)

    if usable(material.get("font_path") or ""):
        return Choice(source="записанный", asked=asked,
                      title=names.get(asked[0], "") if asked else "")

    for number in asked:
        found = find(number, roots)
        if found is not None:
            return Choice(path=str(found).replace("\\", "/"), source="свой",
                          asked=asked, title=names.get(number, ""))

    if usable(spare):
        return Choice(path=spare.replace("\\", "/"), source="запасной", asked=asked)
    return Choice(source="нет", asked=asked)


def stamp(material: dict, path: str) -> bool:
    """Прописывает путь к шрифту во все места, где материал на него ссылается.

    Оформление лежит внутри строки с JSON, поэтому правится подстановкой: так
    остальные байты остаются такими, как их записал CapCut.
    """
    if not path:
        return False

    previous = material.get("font_path") or ""
    material["font_path"] = path
    for entry in material.get("fonts") or []:
        if entry.get("path"):
            previous = previous or entry["path"]
            entry["path"] = path

    content = material.get("content") or ""
    if previous and previous in content:
        patched = content.replace(previous, path)
        try:
            json.loads(patched)
        except ValueError:
            log.warning("Путь шрифта не удалось подставить в оформление, оставляю как было")
        else:
            material["content"] = patched
    return True
