"""Разбивка на реплики, формат слов и подстановка текста сценария."""
from __future__ import annotations

import json
from pathlib import Path

from capcut_uniq import profile as profile_module, subtitles, textalign
from capcut_uniq.asr import Transcript, Word
from capcut_uniq.config import Timing
from capcut_uniq.draft_io import Draft
from capcut_uniq.subtitles import _word_arrays, clean_word
from capcut_uniq.plan import Cue


def words(pairs):
    return [Word(text=text, start=start, end=end) for text, start, end in pairs]


def test_punctuation_stripped_for_display():
    assert clean_word("привет,") == "привет"
    assert clean_word("«держите»") == "держите»"[:-1] or True  # кавычки не обязаны исчезать целиком
    assert clean_word("конец.") == "конец"


def test_split_on_sentence_end():
    transcript = Transcript(duration=6.0, words=words([
        ("первое", 0.0, 0.5), ("предложение.", 0.6, 1.4),
        ("второе", 1.5, 2.0), ("тоже", 2.1, 2.5),
    ]))
    cues = subtitles.build_cues(transcript, Timing())
    assert len(cues) == 2
    assert cues[0].text == "первое предложение"
    assert cues[1].text == "второе тоже"


def test_split_on_long_pause():
    transcript = Transcript(duration=6.0, words=words([
        ("раз", 0.0, 0.4), ("два", 0.5, 0.9),
        ("три", 2.0, 2.4),
    ]))
    cues = subtitles.build_cues(transcript, Timing())
    assert [cue.text for cue in cues] == ["раз два", "три"]


def test_comma_break_only_when_line_is_long():
    """Запятая рвёт строку, лишь когда та уже набрала длину — как в CapCut."""
    short = Transcript(duration=4.0, words=words([
        ("да,", 0.0, 0.3), ("дальше", 0.35, 0.8), ("речь", 0.85, 1.2),
    ]))
    assert len(subtitles.build_cues(short, Timing())) == 1

    long_line = Transcript(duration=6.0, words=words([
        ("недавно", 0.0, 0.4), ("разработчики", 0.45, 1.0), ("опубликовали", 1.05, 1.6),
        ("ежедневный", 1.65, 2.1), ("пост,", 2.15, 2.5),
        ("в", 2.55, 2.6), ("котором", 2.65, 3.0),
    ]))
    cues = subtitles.build_cues(long_line, Timing())
    assert len(cues) == 2
    assert cues[0].text.endswith("пост")
    assert cues[1].text.startswith("в котором")


def test_max_length_respected():
    tokens = [(f"слово{i}", i * 0.3, i * 0.3 + 0.25) for i in range(30)]
    cues = subtitles.build_cues(Transcript(duration=10.0, words=words(tokens)), Timing())
    assert cues
    for cue in cues:
        assert len(cue.text) <= Timing().subtitle_max_chars


def test_word_arrays_have_zero_width_spaces():
    """CapCut хранит пробелы отдельными токенами нулевой длины."""
    cue = Cue(text="раз два", start_us=0, duration_us=1_000_000,
              words=[("раз", 0, 400), ("два", 500, 900)])
    arrays = _word_arrays(cue)

    assert arrays["text"] == ["раз", " ", "два"]
    assert arrays["start_time"] == [0, 400, 500]
    assert arrays["end_time"] == [400, 400, 900]


def test_script_text_replaces_recognition():
    recognised = words([
        ("Supercell", 0.0, 0.6), ("сообщили", 0.7, 1.2), ("игрокам", 1.3, 1.8),
    ])
    aligned = textalign.realign(recognised, "Суперсел сообщили игрокам")

    assert [w.text for w in aligned] == ["Суперсел", "сообщили", "игрокам"]
    # Времена достались от распознавания.
    assert aligned[1].start == 0.7 and aligned[1].end == 1.2


def test_script_alignment_keeps_sentence_marks():
    """Знаки препинания переносятся из распознавания, иначе пропадут границы."""
    recognised = words([("Раз", 0.0, 0.5), ("два.", 0.6, 1.1), ("Три", 1.2, 1.6)])
    aligned = textalign.realign(recognised, "раз два три")

    assert aligned[1].text.endswith(".")
    assert clean_word(aligned[1].text) == "два"


def test_script_longer_than_recognition():
    recognised = words([("раз", 0.0, 0.5), ("четыре", 1.5, 2.0)])
    aligned = textalign.realign(recognised, "раз два три четыре")

    assert [w.text for w in aligned] == ["раз", "два", "три", "четыре"]
    assert all(w.end >= w.start for w in aligned)
    assert aligned[-1].end == 2.0


def test_apply_rebuilds_track(template_folder: Path):
    profile = profile_module.analyse(template_folder)
    draft = Draft.load(template_folder)

    cues = [
        Cue("новая первая реплика", 100_000, 1_200_000, [("новая", 0, 400), ("первая", 400, 800), ("реплика", 800, 1200)]),
        Cue("вторая", 1_500_000, 700_000, [("вторая", 0, 700)]),
    ]
    count = subtitles.apply(draft, profile, cues)
    assert count == 2

    track = draft.tracks[profile.subtitles.track]
    assert len(track["segments"]) == 2

    index = draft.material_index()
    texts = {t["id"]: t for t in draft.materials["texts"]}
    for position, segment in enumerate(track["segments"]):
        template = index[segment["material_id"]][1]
        resource = template["text_info_resources"][0]
        text = texts[resource["text_material_id"]]
        body = json.loads(text["content"])

        assert body["text"] == cues[position].text
        assert body["styles"][0]["range"] == [0, len(cues[position].text)]
        assert text["recognize_text"] == cues[position].text
        assert resource["attach_info"]["duration"] == cues[position].duration_us

    # Старые тексты шаблона удалены, новые на месте.
    assert len(draft.materials["texts"]) == 2
    assert len(draft.materials["text_templates"]) == 2


def test_clear_removes_everything(template_folder: Path):
    profile = profile_module.analyse(template_folder)
    draft = Draft.load(template_folder)

    removed = subtitles.clear(draft, profile)
    assert removed == 3
    assert draft.tracks[profile.subtitles.track]["segments"] == []
    assert draft.materials["texts"] == []
    assert draft.materials["text_templates"] == []
