from elevenlabs_voiceover.chunker import (
    normalize_text,
    split_sentences,
    split_text,
    split_words,
    total_characters,
)


def test_normalize_strips_bom_and_collapses_spaces():
    assert normalize_text("\ufeffПривет   мир  ") == "Привет мир"


def test_normalize_unifies_line_endings():
    assert normalize_text("а\r\nб\rв") == "а\nб\nв"


def test_normalize_collapses_blank_lines():
    assert normalize_text("а\n\n\n\n\nб") == "а\n\nб"


def test_normalize_drops_control_characters():
    assert normalize_text("а\x00\x07б") == "аб"


def test_empty_text_gives_no_chunks():
    assert split_text("", 100) == []
    assert split_text("   \n\n  ", 100) == []


def test_short_text_is_single_chunk():
    chunks = split_text("Одно короткое предложение.", 500)
    assert len(chunks) == 1
    assert chunks[0].text == "Одно короткое предложение."
    assert chunks[0].index == 0


def test_chunks_never_exceed_limit():
    text = " ".join(f"Предложение номер {i} с некоторым содержанием." for i in range(200))
    chunks = split_text(text, 300)
    assert len(chunks) > 1
    assert all(chunk.characters <= 300 for chunk in chunks)


def test_max_chars_overrides_target():
    text = "Слово " * 500
    chunks = split_text(text, 5000, max_chars=250)
    assert all(chunk.characters <= 250 for chunk in chunks)


def test_chunks_are_indexed_sequentially():
    text = " ".join(f"Фраза {i}." for i in range(100))
    chunks = split_text(text, 120)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_no_text_is_lost():
    text = " ".join(f"Предложение {i} тут." for i in range(120))
    chunks = split_text(text, 200)
    rebuilt = " ".join(c.text for c in chunks)
    assert rebuilt.replace("\n\n", " ").split() == normalize_text(text).split()


def test_total_characters_matches_sum():
    chunks = split_text("Раз. Два. Три. " * 50, 100)
    assert total_characters(chunks) == sum(c.characters for c in chunks)


# ----------------------------------------------------------------------
def test_sentences_split_on_punctuation():
    assert split_sentences("Первое. Второе! Третье?") == ["Первое.", "Второе!", "Третье?"]


def test_sentences_keep_closing_quotes():
    result = split_sentences('Он сказал: «Привет!» Потом ушёл.')
    assert result[0].endswith("»")


def test_russian_abbreviation_does_not_split():
    result = split_sentences("Купили хлеб, молоко и т. д. Потом пошли домой.")
    assert len(result) == 2
    assert "т. д." in result[0]


def test_initials_do_not_split():
    result = split_sentences("Читаем А. С. Пушкина каждый день. Это полезно.")
    assert len(result) == 2
    assert "А. С. Пушкина" in result[0]


def test_english_abbreviation_does_not_split():
    result = split_sentences("Meet Dr. Smith tomorrow. He is waiting.")
    assert len(result) == 2


def test_ellipsis_ends_sentence():
    result = split_sentences("Он задумался… Затем ответил.")
    assert len(result) == 2


def test_prefix_abbreviation_before_proper_noun_does_not_split():
    result = split_sentences("Он живёт на ул. Ленина рядом с парком.")
    assert len(result) == 1


def test_terminal_abbreviation_before_capital_splits():
    result = split_sentences("Пришли Иванов, Петров и др. Затем начали работу.")
    assert len(result) == 2


def test_terminal_abbreviation_inside_sentence_does_not_split():
    result = split_sentences("Взяли книги, тетради и др. канцелярию для школы.")
    assert len(result) == 1


def test_compound_abbreviation_ends_sentence():
    result = split_sentences("Нужны хлеб, соль и т. п. Список закрыт.")
    assert len(result) == 2


# ----------------------------------------------------------------------
def test_long_sentence_split_by_words():
    sentence = " ".join(["слово"] * 100)
    parts = split_words(sentence, 60)
    assert all(len(p) <= 60 for p in parts)
    assert " ".join(parts).split() == sentence.split()


def test_single_giant_word_is_hard_split():
    parts = split_words("я" * 500, 100)
    assert all(len(p) <= 100 for p in parts)
    assert "".join(parts) == "я" * 500


def test_giant_word_inside_text_does_not_break_limit():
    text = "Начало. " + "ц" * 900 + " Конец."
    chunks = split_text(text, 200)
    assert all(chunk.characters <= 200 for chunk in chunks)


def test_paragraph_boundaries_are_preferred():
    text = "Первый абзац тут.\n\nВторой абзац тут."
    chunks = split_text(text, 20)
    assert len(chunks) == 2
    assert chunks[0].text == "Первый абзац тут."
    assert chunks[1].text == "Второй абзац тут."


def test_paragraphs_joined_when_they_fit():
    text = "Раз.\n\nДва."
    chunks = split_text(text, 500)
    assert len(chunks) == 1
    assert "\n\n" in chunks[0].text
