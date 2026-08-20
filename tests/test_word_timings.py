"""Времена слов и длительность реплик.

Распознавание нередко не слышит часть сценария — особенно хвост. Раньше таким
словам не доставалось времени вообще: они сваливались в одну точку, реплика
получала нулевую длительность и на экране её просто не было. Субтитр при этом
исправно лежал в черновике, из-за чего поломку было не видно ни в журнале, ни в
самопроверке.
"""
from __future__ import annotations

from capcut_uniq import subtitles, textalign
from capcut_uniq.asr import Transcript, Word
from capcut_uniq.config import Timing
from capcut_uniq.subtitles import MIN_CUE_US
from capcut_uniq.textalign import MIN_WORD


def words(pairs):
    return [Word(text=text, start=start, end=end) for text, start, end in pairs]


HEARD = words([
    ("В", 0.00, 0.20), ("Brawl", 0.25, 0.60), ("Stars", 0.65, 1.00),
    ("появилась", 1.05, 1.60), ("раздача.", 1.70, 2.30),
    ("Об", 2.60, 2.75), ("этом", 2.80, 3.05),
    ("знают", 3.10, 3.50), ("немногие.", 3.55, 4.20),
])
SCRIPT = ("Бравл Старс спрятали способ получить награду "
          "об этом пока знают немногие хотя разработчики уже поделились разгадкой")


def test_no_word_collapses_to_zero():
    aligned = textalign.realign(HEARD, SCRIPT, duration=6.4)
    assert len(aligned) == len(SCRIPT.split())
    for word in aligned:
        assert word.end - word.start >= MIN_WORD - 1e-9, word.text


def test_tail_words_get_the_rest_of_the_audio():
    """Хвост сценария, который не услышали, раскладывается до конца озвучки."""
    aligned = textalign.realign(HEARD, SCRIPT, duration=6.4)
    tail = aligned[-5:]

    assert [w.text for w in tail] == ["хотя", "разработчики", "уже", "поделились", "разгадкой"]
    assert tail[0].start >= HEARD[-1].end - 1e-9
    assert tail[-1].end <= 6.4 + 1e-6
    # Времена идут по возрастанию, а не стоят на месте.
    assert all(a.start < b.start for a, b in zip(tail, tail[1:]))


def test_times_stay_monotonic():
    aligned = textalign.realign(HEARD, SCRIPT, duration=6.4)
    for previous, current in zip(aligned, aligned[1:]):
        assert current.start >= previous.start - 1e-9


def test_no_cue_is_invisible():
    aligned = textalign.realign(HEARD, SCRIPT, duration=6.4)
    cues = subtitles.build_cues(Transcript(duration=6.4, words=aligned), Timing())

    assert cues
    for cue in cues:
        assert cue.duration_us >= 150_000, (cue.text, cue.duration_us)


def test_short_cue_is_widened_without_touching_the_next():
    aligned = textalign.realign(HEARD, SCRIPT, duration=6.4)
    cues = subtitles.build_cues(Transcript(duration=6.4, words=aligned), Timing())

    for current, following in zip(cues, cues[1:]):
        assert current.start_us + current.duration_us <= following.start_us


def test_widening_respects_a_tight_neighbour():
    """Если следующая реплика близко, растягиваем лишь до неё."""
    cues = [
        subtitles.Cue("первая", 0, 1_000, [("первая", 0, 1)]),
        subtitles.Cue("вторая", 200_000, 500_000, [("вторая", 0, 500)]),
    ]
    subtitles._widen_short(cues)

    assert cues[0].duration_us < MIN_CUE_US
    assert cues[0].start_us + cues[0].duration_us <= cues[1].start_us


def test_alignment_without_audio_duration_still_works():
    """Длину озвучки могли не передать — падать нельзя."""
    aligned = textalign.realign(HEARD, SCRIPT)
    assert len(aligned) == len(SCRIPT.split())
    for word in aligned:
        assert word.end > word.start
