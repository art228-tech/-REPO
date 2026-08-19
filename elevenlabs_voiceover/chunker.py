"""Нарезка длинного текста на куски под один запрос к API.

Правило приоритетов при разрезании: абзац, затем предложение, затем слово и
только в крайнем случае — разрыв посреди слова. Резать по границе предложения
важно не только ради аккуратных стыков: модель строит интонацию по всему куску
сразу, и обрубок фразы звучит неестественно.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Sequence

#: Сокращения, за которыми предложение почти никогда не кончается: после них
#: обязательно идёт то, к чему они относятся («ул. Ленина», «Dr. Smith»).
_PREFIX_ABBREVIATIONS = {
    # русские
    "т", "тт", "см", "стр", "рис", "табл", "гл", "им", "ул", "д", "г", "в", "н", "э",
    "руб", "коп", "тыс", "млн", "млрд", "проф", "акад", "доц", "чл", "корр", "зам",
    "зав", "мин", "макс", "обл", "респ", "изд", "сост", "ред", "кв",
    # английские
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "inc", "ltd", "co", "fig",
    "no", "vol", "ed", "pp", "dept", "univ", "approx",
}

#: Сокращения, которыми предложение вполне может заканчиваться («и т. д.»,
#: «и др.»). После них разрешаем разрез, если дальше начинается новая фраза.
_TERMINAL_ABBREVIATIONS = {"др", "пр", "гг", "вв", "etc", "eg", "ie", "vs"}

#: Вторые части составных сокращений: «т. д.», «т. п.», «т. е.».
_COMPOUND_TAILS = {"д", "п", "е"}
_COMPOUND_HEAD = re.compile(r"(?:^|\W)т\s*\.\s*$")

_SENTENCE_END = re.compile(r"([.!?…]+)([\"'»”’)\]]*)(\s+)")
_PARAGRAPH_SPLIT = re.compile(r"\n[ \t]*\n+")
_WHITESPACE_RUN = re.compile(r"[ \t\u00a0]+")
_TRAILING_SPACES = re.compile(r"[ \t\u00a0]+(\n)")


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str

    @property
    def characters(self) -> int:
        return len(self.text)


#: Переносы строк отдаются модели как есть — она делает на них паузу.
LINE_BREAKS_KEEP = "keep"
#: Переносы внутри абзаца превращаются в пробел, пустая строка остаётся.
LINE_BREAKS_SOFT = "soft"
#: Весь текст сводится в один сплошной абзац.
LINE_BREAKS_ALL = "all"

LINE_BREAK_MODES = {
    LINE_BREAKS_KEEP: "Оставлять как есть — на них будет пауза",
    LINE_BREAKS_SOFT: "Убирать внутри абзаца, пустую строку оставлять",
    LINE_BREAKS_ALL: "Убирать все, читать сплошным текстом",
}

#: Метка, которой временно подменяются границы абзацев при чистке.
_PARAGRAPH_MARK = "\x00"


def count_line_breaks(raw: str) -> int:
    """Сколько переносов строк внутри абзацев — именно они дают паузы."""
    if not raw:
        return 0
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = _PARAGRAPH_SPLIT.sub(_PARAGRAPH_MARK, text)
    return text.count("\n")


def normalize_text(raw: str, line_breaks: str = LINE_BREAKS_KEEP) -> str:
    """Убрать BOM, невидимые символы и лишние пробелы.

    Каждый лишний символ — это списанный кредит, поэтому чистка тут не
    косметика, а экономия. Переносы строк трогаем только по просьбе: модель
    делает на них паузу, и для одних текстов это нужно, для других мешает.
    """
    if not raw:
        return ""

    text = raw.replace("\ufeff", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Управляющие символы (кроме перевода строки и табуляции) ломают разметку
    # запроса и всё равно не произносятся.
    text = "".join(
        ch for ch in text if ch in "\n\t" or not unicodedata.category(ch).startswith("C")
    )

    if line_breaks == LINE_BREAKS_ALL:
        text = re.sub(r"\n+", " ", text)
    elif line_breaks == LINE_BREAKS_SOFT:
        # Границы абзацев прячем, чтобы уцелели, остальные переносы — в пробел.
        text = _PARAGRAPH_SPLIT.sub(_PARAGRAPH_MARK, text)
        text = text.replace("\n", " ")
        text = text.replace(_PARAGRAPH_MARK, "\n\n")

    text = _WHITESPACE_RUN.sub(" ", text)
    text = _TRAILING_SPACES.sub(r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_sentences(paragraph: str) -> List[str]:
    """Разбить абзац на предложения, не спотыкаясь о сокращения."""
    if not paragraph:
        return []

    sentences: List[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(paragraph):
        end = match.end(2)
        candidate = paragraph[start:end].strip()
        if not candidate:
            continue
        if _looks_like_abbreviation(paragraph, match.start(1)):
            continue
        sentences.append(candidate)
        start = match.end()

    tail = paragraph[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences or [paragraph.strip()]


def _looks_like_abbreviation(text: str, dot_index: int) -> bool:
    """Проверить, что точка на позиции dot_index закрывает сокращение.

    При сомнениях отвечаем «да»: лишний разрез посреди фразы портит интонацию
    сильнее, чем пропущенная граница — та просто оставит кусок чуть длиннее.
    """
    if text[dot_index] != ".":
        return False

    left = dot_index
    while left > 0 and (text[left - 1].isalpha() or text[left - 1] == "."):
        left -= 1
    raw_word = text[left:dot_index].strip(".")
    word = raw_word.lower()
    if not word:
        return False

    # Одиночная заглавная буква — инициал: «А. С. Пушкин».
    if len(raw_word) == 1 and raw_word.isupper():
        return True

    starts_new_sentence = _next_char_starts_sentence(text, dot_index)

    # Хвост составного сокращения: «и т. д.», «и т. п.», «т. е.».
    if word in _COMPOUND_TAILS and _COMPOUND_HEAD.search(text[:left]):
        return not starts_new_sentence

    if word in _TERMINAL_ABBREVIATIONS:
        return not starts_new_sentence

    if word in _PREFIX_ABBREVIATIONS:
        return True

    # Прочие одиночные строчные буквы трактуем как сокращение.
    return len(word) == 1 and word.isalpha()


def _next_char_starts_sentence(text: str, dot_index: int) -> bool:
    """Похоже ли, что после точки начинается новое предложение."""
    index = dot_index + 1
    while index < len(text) and (text[index].isspace() or text[index] in "\"'»”’)]"):
        index += 1
    if index >= len(text):
        return True
    char = text[index]
    return char.isupper() or char in "«\"'-—"


def split_words(sentence: str, limit: int) -> List[str]:
    """Разрезать слишком длинное предложение по словам."""
    words = sentence.split(" ")
    parts: List[str] = []
    current: List[str] = []
    current_len = 0

    for word in words:
        if len(word) > limit:
            if current:
                parts.append(" ".join(current))
                current, current_len = [], 0
            parts.extend(_hard_split(word, limit))
            continue

        addition = len(word) + (1 if current else 0)
        if current_len + addition > limit and current:
            parts.append(" ".join(current))
            current, current_len = [word], len(word)
        else:
            current.append(word)
            current_len += addition

    if current:
        parts.append(" ".join(current))
    return parts


def _hard_split(token: str, limit: int) -> List[str]:
    return [token[i : i + limit] for i in range(0, len(token), limit)] or [token]


def _atomize(text: str, limit: int) -> List[tuple]:
    """Разложить текст на минимальные неделимые куски с разделителями.

    Возвращает список пар (separator_before, fragment).
    """
    atoms: List[tuple] = []
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if p.strip()]

    for p_index, paragraph in enumerate(paragraphs):
        paragraph_sep = "\n\n" if p_index > 0 else ""
        pieces: List[str]

        if len(paragraph) <= limit:
            pieces = [paragraph]
        else:
            pieces = []
            for sentence in split_sentences(paragraph):
                if len(sentence) <= limit:
                    pieces.append(sentence)
                else:
                    pieces.extend(split_words(sentence, limit))

        for s_index, piece in enumerate(pieces):
            sep = paragraph_sep if s_index == 0 else " "
            atoms.append((sep, piece))

    return atoms


def split_text(
    text: str,
    target_chars: int,
    max_chars: int = 0,
    line_breaks: str = LINE_BREAKS_KEEP,
) -> List[Chunk]:
    """Разбить текст на куски не длиннее лимита, стараясь попасть в target.

    target_chars — желаемый размер куска, max_chars — жёсткий предел модели.
    """
    normalized = normalize_text(text, line_breaks)
    if not normalized:
        return []

    limit = int(target_chars)
    if max_chars and max_chars > 0:
        limit = min(limit, int(max_chars))
    limit = max(1, limit)

    if len(normalized) <= limit:
        return [Chunk(index=0, text=normalized)]

    atoms = _atomize(normalized, limit)

    chunks: List[str] = []
    current = ""

    for sep, fragment in atoms:
        if not current:
            current = fragment
            continue
        candidate_len = len(current) + len(sep) + len(fragment)
        if candidate_len <= limit:
            current = f"{current}{sep}{fragment}"
        else:
            chunks.append(current)
            current = fragment

    if current:
        chunks.append(current)

    return [Chunk(index=i, text=c) for i, c in enumerate(chunks) if c.strip()]


def total_characters(chunks: Sequence[Chunk]) -> int:
    return sum(chunk.characters for chunk in chunks)
