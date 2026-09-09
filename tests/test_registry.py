"""Реестр собранных роликов — машинная копия того, что уходит в журнал.

По нему загрузчик телеграм-бота узнаёт, чем ролик отличается от соседнего:
экспортированный из CapCut файл несёт только имя, а фон, папка озвучки, музыка
и длительность QR лежат здесь. Ошибка в реестре не видна на глаз и всплывает
уже кривой статистикой, поэтому поля проверяются поимённо.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from capcut_uniq import plan as plan_module, profile as profile_module, registry
from capcut_uniq.asr import Transcript, Word
from capcut_uniq.config import Config


class _Decor:
    def __init__(self, duration_us: int):
        self.duration_us = duration_us


class _Plan:
    """План ролика в объёме, который читает реестр."""

    def __init__(self, *, voice: Path, black: bool = False,
                 music: object | None = None, qr: object | None = None):
        self.voice_path = voice
        self.black_background = black
        self.music = music
        self.qr = qr


def _plan(**kwargs) -> _Plan:
    kwargs.setdefault("voice", Path("D:/озвучки/необыч/vo_07.mp3"))
    kwargs.setdefault("music", object())
    kwargs.setdefault("qr", _Decor(2_500_000))
    return _Plan(**kwargs)


def test_entry_carries_every_field_the_bot_needs():
    """Пять признаков ролика плюс имя — на них строится вся статистика."""
    record = registry.entry("auto_0906_1420_007", _plan(), 14_320_000, "0813-01")

    assert record["name"] == "auto_0906_1420_007"
    assert record["duration_s"] == 14.32
    assert record["background"] == "blur"
    assert record["voice_folder"] == "необыч"
    assert record["music"] is True
    assert record["qr_s"] == 2.5


def test_voice_folder_is_the_folder_the_voice_came_from():
    """Папку выбирает пользователь, и по ней же он потом читает статистику."""
    record = registry.entry("x", _plan(voice=Path("D:/озвучки/обыч/vo_01.mp3")), 1, "t")
    assert record["voice_folder"] == "обыч"


def test_black_background_is_told_apart_from_blurred():
    assert registry.entry("x", _plan(black=True), 1, "t")["background"] == "black"
    assert registry.entry("x", _plan(black=False), 1, "t")["background"] == "blur"


def test_missing_music_and_qr_do_not_break_the_record():
    """Шаблон без музыки или без QR — обычное дело, а не повод падать."""
    record = registry.entry("x", _plan(music=None, qr=None), 1, "t")
    assert record["music"] is False
    assert record["qr_s"] == 0.0


def test_entry_reads_a_real_render_plan(template_folder: Path):
    """Поля берутся из настоящего плана, а не из тестовой заглушки.

    Заглушка согласится с любым переименованием внутри плана и промолчит, а
    реестр после такого начнёт писать пустые данные — заметно это станет только
    по статистике, собранной за неделю.
    """
    profile = profile_module.analyse(template_folder)
    config = Config(clips_dir=Path("."), voice_dir=Path("."))
    transcript = Transcript(duration=13.0,
                            words=[Word(text="фраза.", start=0.0, end=2.0)])
    line = plan_module.timeline(profile, config, transcript, trailing_silence_s=0.0)
    built = plan_module.build(
        profile, config, line, Path("D:/озвучки/обыч/vo_01.mp3"),
        [Path("a.mp4"), Path("b.mp4")], [30.0, 30.0], random.Random(1),
    )

    record = registry.entry("ролик", built, built.total_us, profile.name)

    assert record["voice_folder"] == "обыч"
    assert record["background"] == "blur"
    assert record["music"] is True
    assert record["qr_s"] > 0
    assert record["duration_s"] == round(built.total_us / 1_000_000, 3)


def test_records_are_appended_one_per_line(tmp_path: Path):
    """Строка на ролик: оборванная запись портит себя, а не весь реестр."""
    registry.append(tmp_path, {"name": "первый"})
    registry.append(tmp_path, {"name": "второй"})

    lines = registry.path_for(tmp_path).read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["name"] for line in lines] == ["первый", "второй"]


def test_russian_names_stay_readable_in_the_file(tmp_path: Path):
    """Реестр иногда открывают глазами — экранированные коды там ни к чему."""
    registry.append(tmp_path, {"name": "ролик", "voice_folder": "необыч"})
    assert "необыч" in registry.path_for(tmp_path).read_text(encoding="utf-8")


def test_reading_an_absent_registry_gives_nothing(tmp_path: Path):
    """До первой сборки файла нет — загрузчик должен пережить это молча."""
    assert registry.read(tmp_path) == {}


def test_broken_line_does_not_take_the_rest_with_it(tmp_path: Path):
    """Запись могла оборваться на выключении — остальные ролики не виноваты."""
    registry.append(tmp_path, {"name": "целый"})
    with registry.path_for(tmp_path).open("a", encoding="utf-8") as handle:
        handle.write('{"name": "обор\n')
    registry.append(tmp_path, {"name": "тоже целый"})

    found = registry.read(tmp_path)
    assert sorted(found) == ["тоже целый", "целый"]


def test_rebuilt_video_wins_over_the_old_record(tmp_path: Path):
    """В папке черновиков лежит последняя сборка — её данные и верны."""
    registry.append(tmp_path, {"name": "ролик", "background": "blur"})
    registry.append(tmp_path, {"name": "ролик", "background": "black"})

    assert registry.read(tmp_path)["ролик"]["background"] == "black"
