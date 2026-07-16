"""Тесты проверяемых на Linux модулей: субтитры, ассеты, состояние, лимиты."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoshorts.assets import AssetPool, BackgroundSlicer  # noqa: E402
from autoshorts.config import FolderRule  # noqa: E402
from autoshorts.state import StateStore  # noqa: E402
from autoshorts.subtitles import (SubtitleStyle, Word, build_ass,  # noqa: E402
                                   parse_script_words)
from autoshorts.voice.base import (clamp_voice_description,  # noqa: E402
                                   split_text_for_tts)


def test_state_atomic_roundtrip(tmp_path):
    store = StateStore(tmp_path / "s.json")
    store.set("a", 1)
    store.update(b=2, c=[1, 2, 3])
    reopened = StateStore(tmp_path / "s.json")
    assert reopened.get("a") == 1
    assert reopened.get("b") == 2
    assert reopened.get("c") == [1, 2, 3]


def test_state_survives_corruption(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{ broken json", encoding="utf-8")
    store = StateStore(p)  # не должно падать
    assert store.get("x", "def") == "def"
    store.set("x", 5)
    assert StateStore(p).get("x") == 5


def test_assets_cycle_mode(tmp_path):
    d = tmp_path / "bg"
    d.mkdir()
    for i in range(3):
        (d / f"{i}.mp4").write_bytes(b"x")
    state = StateStore(tmp_path / "st.json")
    pool = AssetPool("backgrounds", FolderRule(str(d), "cycle"), state)
    picks = [pool.next().name for _ in range(4)]
    assert picks == ["0.mp4", "1.mp4", "2.mp4", "0.mp4"]  # по кругу


def test_assets_consume_mode(tmp_path):
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "a.txt").write_text("hi", encoding="utf-8")
    state = StateStore(tmp_path / "st.json")
    pool = AssetPool("scripts", FolderRule(str(d), "consume"), state)
    chosen = pool.next()
    assert chosen.name == "a.txt"
    pool.mark_consumed(chosen)
    assert pool.next() is None  # файл удалён


def test_background_slicer_offsets(tmp_path):
    d = tmp_path / "bg"
    d.mkdir()
    (d / "clip.mp4").write_bytes(b"x")
    state = StateStore(tmp_path / "st.json")
    pool = AssetPool("backgrounds", FolderRule(str(d), "cycle"), state)
    slicer = BackgroundSlicer(pool, state, segment_sec=10)
    # длительность 25с -> отрезки 0..10, 10..20, 20..25, затем сброс 0..10
    lengths = []
    for _ in range(4):
        _, start, length = slicer.next_segment(lambda p: 25.0)
        lengths.append((round(start, 1), round(length, 1)))
    assert lengths == [(0.0, 10.0), (10.0, 10.0), (20.0, 5.0), (0.0, 10.0)]


def test_clamp_voice_description():
    assert len(clamp_voice_description("x", 20, 1000)) >= 20
    long = "word " * 500
    assert len(clamp_voice_description(long, 20, 100)) <= 100


def test_split_text_for_tts():
    assert split_text_for_tts("Short.", 100) == ["Short."]
    text = "Предложение раз. Предложение два. Предложение три."
    chunks = split_text_for_tts(text, 25)
    assert all(len(c) <= 25 for c in chunks)
    assert "".join(chunks).replace(" ", "") != ""


def test_build_ass_has_dialogue_and_highlight():
    words = [
        Word("топ", 0.0, 0.4, highlight=True),
        Word("заняли", 0.4, 0.9),
    ]
    style = SubtitleStyle(glow=True, glow_strength=3)
    ass = build_ass(words, style, play_res=(1080, 1920), words_per_cue=2)
    assert "[V4+ Styles]" in ass
    assert "Dialogue:" in ass
    assert "\\blur3" in ass          # свечение
    assert "\\c&H00" in ass          # подсветка ключевого слова


def test_content_size_aspect():
    from autoshorts.montage.ffmpeg_render import _content_size
    w, h = _content_size(1080, (5, 6))
    assert w == 1080
    assert h == 1296          # 1080*6/5
    assert h % 2 == 0         # чётная высота для libx264


def test_parse_script_words_marks_highlight():
    text = "это [[топ]] видео"
    timings = [
        {"word": "это", "start": 0, "end": 0.3},
        {"word": "топ", "start": 0.3, "end": 0.6},
        {"word": "видео", "start": 0.6, "end": 1.0},
    ]
    words = parse_script_words(text, timings)
    hl = {w.text: w.highlight for w in words}
    assert hl["топ"] is True
    assert hl["это"] is False
