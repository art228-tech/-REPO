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


def test_words_end_exactly_at_the_cue_edge():
    """Ключевой инвариант CapCut: последнее слово кончается на краю реплики.

    От него отсчитывает анимация подписи. В рабочих шаблонах он выполняется во
    всех репликах без исключения, и при расхождении текст на экране не появлялся.
    """
    cue = subtitles.Cue("раз два три", 0, 1_000_000,
                        [("раз", 0, 900), ("два", 900, 1800), ("три", 1800, 2600)])
    arrays = subtitles._word_arrays(cue)

    assert max(arrays["end_time"]) == 1000
    assert arrays["text"] == ["раз", " ", "два", " ", "три"]


def test_words_are_stretched_when_they_fall_short():
    cue = subtitles.Cue("раз два", 0, 2_000_000, [("раз", 0, 100), ("два", 100, 200)])
    arrays = subtitles._word_arrays(cue)
    assert max(arrays["end_time"]) == 2000


def test_words_without_times_are_spread_evenly():
    cue = subtitles.Cue("раз два", 0, 1_000_000, [("раз", 0, 0), ("два", 0, 0)])
    arrays = subtitles._word_arrays(cue)
    assert max(arrays["end_time"]) == 1000
    assert arrays["start_time"][0] == 0


def test_word_order_never_reverses():
    cue = subtitles.Cue("а б в", 0, 500_000,
                        [("а", 0, 3000), ("б", 3000, 6000), ("в", 6000, 9000)])
    arrays = subtitles._word_arrays(cue)
    assert arrays["start_time"] == sorted(arrays["start_time"])
    assert all(e >= s for s, e in zip(arrays["start_time"], arrays["end_time"]))


def test_invariant_is_checked_by_validation(template_folder):
    """Самопроверка должна ловить расхождение слов с краем реплики."""
    from capcut_uniq import validate
    from capcut_uniq.draft_io import Draft

    draft = Draft.load(template_folder)
    text = draft.materials["texts"][0]
    text["words"] = {"start_time": [0], "end_time": [9_999], "text": ["слово"]}
    draft.save()

    report = validate.check(template_folder)
    assert not report.ok
    assert any("слова кончаются" in item for item in report.errors)


def test_alignment_without_audio_duration_still_works():
    """Длину озвучки могли не передать — падать нельзя."""
    aligned = textalign.realign(HEARD, SCRIPT)
    assert len(aligned) == len(SCRIPT.split())
    for word in aligned:
        assert word.end > word.start
