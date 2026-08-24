"""Поиск настоящего файла шрифта для субтитра.

Шаблоны сделаны на телефоне, поэтому шрифт в них записан телефонным путём, и на
ноутбуке такой папки нет. Пока субтитр шёл через текстовый шаблон, шрифт брался
из его ресурсов — там путь настоящий. Как только субтитр стал обычным текстом,
эта ссылка ушла, и CapCut начал подставлять свой шрифт, один и тот же во всех
проектах.
"""
from __future__ import annotations

import json
from pathlib import Path

from capcut_uniq import fonts

# Ровно так шрифт записан в настоящем шаблоне, снятом с телефона.
PHONE = ("/data/user/0/com.lemon.lvoverseas/files/resources/effect/artists/"
         "7579481374890003713/0b5a0704565a89aa6291be6bad0cfda1/font.ttf")

CONTENT = (
    '{"styles":[{"fill":{"content":{"solid":{"color":[1,1,1]}}},"range":[0,5],'
    '"size":12,"font":{"path":"' + PHONE + '","id":"7579481374890003713"}}],'
    '"text":"Слово"}'
)


def _material() -> dict:
    return {
        "font_path": PHONE,
        "font_name": "",
        "fonts": [{"resource_id": "7579481374890003713", "path": PHONE,
                   "title": "Блок-Hv"}],
        "content": CONTENT,
    }


class _Draft:
    """Черновик в объёме, который нужен поиску кэша."""

    def __init__(self, resources: list[dict]):
        self.materials = {"text_templates": [{"resources": resources}]}


def _cache(tmp_path: Path) -> Path:
    root = tmp_path / "User Data" / "Cache" / "effect"
    root.mkdir(parents=True)
    return root


def _put(root: Path, resource_id: str, name: str = "font.ttf") -> Path:
    folder = root / resource_id / "81733827a8cb7523177fe2ed96c16d51"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"\x00\x01OTTO")
    return path


def test_cache_root_is_taken_from_the_draft(tmp_path: Path):
    """Корень кэша не угадывается: CapCut сам записал его в черновик."""
    root = _cache(tmp_path)
    draft = _Draft([{"panel": "fonts", "path": f"{root}/7256628603268370945/xx/ZY.ttf"}])
    assert fonts.cache_roots(draft) == [root]


def test_cache_root_is_found_next_to_the_drafts_folder(tmp_path: Path):
    """Черновики лежат в User Data/Projects, кэш — в User Data/Cache/effect."""
    root = _cache(tmp_path)
    drafts = tmp_path / "User Data" / "Projects" / "com.lveditor.draft"
    drafts.mkdir(parents=True)
    assert root in fonts.cache_roots(_Draft([]), drafts)


def test_font_is_found_by_its_resource_number(tmp_path: Path):
    root = _cache(tmp_path)
    wanted = _put(root, "7579481374890003713")
    _put(root, "7256628603268370945", "ZY Innocent.ttf")
    assert fonts.find("7579481374890003713", [root]) == wanted


def test_missing_font_gives_nothing(tmp_path: Path):
    root = _cache(tmp_path)
    assert fonts.find("7579481374890003713", [root]) is None
    assert fonts.find("", [root]) is None


def test_material_asks_for_its_own_font():
    assert fonts.wanted(_material()) == ["7579481374890003713"]


def test_own_font_wins_when_it_is_on_disk(tmp_path: Path):
    """У каждого шаблона должен остаться свой шрифт, а не общий запасной."""
    root = _cache(tmp_path)
    own = _put(root, "7579481374890003713")
    spare = _put(root, "7256628603268370945", "ZY Innocent.ttf")

    chosen = fonts.resolve(_material(), [root], str(spare))
    assert chosen == str(own).replace("\\", "/")


def test_template_font_is_the_spare(tmp_path: Path):
    """Своего шрифта нет — берём тот, которым шаблон и рисовался."""
    root = _cache(tmp_path)
    spare = _put(root, "7256628603268370945", "ZY Innocent.ttf")

    chosen = fonts.resolve(_material(), [root], str(spare))
    assert chosen == str(spare).replace("\\", "/")


def test_nothing_to_do_when_the_recorded_path_opens(tmp_path: Path):
    root = _cache(tmp_path)
    real = _put(root, "7579481374890003713")
    material = _material()
    material["font_path"] = str(real)

    assert fonts.resolve(material, [root], "") == ""


def test_no_font_anywhere_gives_nothing(tmp_path: Path):
    root = _cache(tmp_path)
    assert fonts.resolve(_material(), [root], "") == ""
    assert fonts.resolve(_material(), [root], "/нет/такого/файла.ttf") == ""


def test_path_is_written_everywhere_it_is_referenced(tmp_path: Path):
    root = _cache(tmp_path)
    real = str(_put(root, "7579481374890003713")).replace("\\", "/")
    material = _material()

    assert fonts.stamp(material, real)
    assert material["font_path"] == real
    assert material["fonts"][0]["path"] == real

    body = json.loads(material["content"])
    assert body["styles"][0]["font"]["path"] == real
    # Телефонного пути не осталось нигде.
    assert PHONE not in material["content"]


def test_stamping_keeps_the_rest_of_the_bytes(tmp_path: Path):
    """Правится только путь: остальное должно остаться как записал CapCut."""
    root = _cache(tmp_path)
    real = str(_put(root, "7579481374890003713")).replace("\\", "/")
    material = _material()
    fonts.stamp(material, real)

    assert material["content"] == CONTENT.replace(PHONE, real)
    assert '": ' not in material["content"]

    body = json.loads(material["content"])
    assert body["text"] == "Слово"
    assert body["styles"][0]["range"] == [0, 5]
    assert body["styles"][0]["size"] == 12


def test_stamping_nothing_changes_nothing():
    material = _material()
    assert not fonts.stamp(material, "")
    assert material["content"] == CONTENT
    assert material["font_path"] == PHONE
