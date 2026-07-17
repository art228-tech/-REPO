"""Генерация субтитров в формате ASS (libass) по словам.

Стиль «Сияние»: белый шрифт «блок» со свечением, обычно без обводки
(есть запасной вариант с чёрной обводкой). Ключевые слова, помеченные в
скрипте как [[слово]], подсвечиваются другим цветом.

Тайминги берутся из word-timestamps озвучки ElevenLabs (или из выравнивания),
поэтому субтитры синхронны без ручной подгонки.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

HIGHLIGHT_RE = re.compile(r"\[\[(.+?)\]\]")


@dataclass
class Word:
    text: str
    start: float  # секунды
    end: float
    highlight: bool = False


@dataclass
class SubtitleStyle:
    font: str = "Arial"
    font_size: int = 96
    primary_color: str = "FFFFFF"      # RRGGBB
    outline: int = 0
    outline_color: str = "000000"
    glow: bool = True
    glow_color: str = "8A2BE2"
    glow_strength: int = 3
    highlight_color: str = "39FF14"
    align: int = 2                      # 2 = снизу по центру (ASS numpad)
    margin_v: int = 220                 # отступ снизу (center_lower)
    bold: bool = True


def _rrggbb_to_ass(color: str) -> str:
    """RRGGBB -> &H00BBGGRR (ASS хранит цвет как AABBGGRR, AA=00 непрозрачно)."""
    color = color.strip().lstrip("#")
    if len(color) != 6:
        color = "FFFFFF"
    r, g, b = color[0:2], color[2:4], color[4:6]
    return f"&H00{b}{g}{r}".upper()


def _fmt_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    cs = int(round(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def parse_script_words(text: str, per_word_timings: list[dict]) -> list[Word]:
    """Собрать список Word из текста и таймингов.

    per_word_timings — список вида [{"word": "...", "start": s, "end": e}, ...]
    (как отдаёт выравнивание/озвучка). Маркеры [[...]] в исходном тексте
    задают подсветку; здесь они уже должны быть сопоставлены со словами
    вызывающей стороной. Если подсветку не передали — вычислим по тексту.
    """
    highlighted = {m.group(1).strip().lower()
                   for m in HIGHLIGHT_RE.finditer(text)}
    words: list[Word] = []
    for item in per_word_timings:
        raw = str(item.get("word", "")).strip()
        if not raw:
            continue
        clean = raw.strip(".,!?;:—-\"'()»«")
        words.append(Word(
            text=clean,
            start=float(item["start"]),
            end=float(item["end"]),
            highlight=clean.lower() in highlighted,
        ))
    return words


def _cue_text(words: list[Word], style: SubtitleStyle) -> str:
    primary = _rrggbb_to_ass(style.primary_color)
    highlight = _rrggbb_to_ass(style.highlight_color)
    parts = []
    for w in words:
        if w.highlight:
            parts.append(f"{{\\c{highlight}}}{w.text}{{\\c{primary}}}")
        else:
            parts.append(w.text)
    body = " ".join(parts)
    prefix = ""
    if style.glow:
        # Свечение: мягкий размытый цветной контур поверх белого текста.
        prefix = f"{{\\blur{style.glow_strength}}}"
    return prefix + body


def build_ass(words: list[Word], style: SubtitleStyle,
              play_res: tuple[int, int] = (1080, 1920),
              words_per_cue: int = 2) -> str:
    """Собрать содержимое .ass файла."""
    w, h = play_res
    primary = _rrggbb_to_ass(style.primary_color)
    # Цвет контура: при glow используем цвет свечения, иначе цвет обводки.
    outline_col = _rrggbb_to_ass(style.glow_color if style.glow
                                 else style.outline_color)
    outline_w = style.glow_strength if (style.glow and style.outline == 0) \
        else style.outline
    bold = -1 if style.bold else 0

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{style.font},{style.font_size},{primary},{primary},{outline_col},&H00000000,{bold},0,0,0,100,100,0,0,1,{outline_w},0,{style.align},60,60,{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]
    for i in range(0, len(words), words_per_cue):
        group = words[i:i + words_per_cue]
        if not group:
            continue
        start = _fmt_time(group[0].start)
        end = _fmt_time(group[-1].end)
        text = _cue_text(group, style)
        lines.append(f"Dialogue: 0,{start},{end},Main,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"


def write_ass(words: list[Word], style: SubtitleStyle, out_path: str | Path,
              play_res: tuple[int, int] = (1080, 1920),
              words_per_cue: int = 2) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_ass(words, style, play_res, words_per_cue),
                   encoding="utf-8")
    return out


def style_from_config(style_cfg: dict) -> SubtitleStyle:
    return SubtitleStyle(
        font=style_cfg.get("font", "Arial"),
        font_size=int(style_cfg.get("font_size", 96)),
        primary_color=str(style_cfg.get("primary_color", "FFFFFF")),
        outline=int(style_cfg.get("outline", 0)),
        outline_color=str(style_cfg.get("outline_color", "000000")),
        glow=bool(style_cfg.get("glow", True)),
        glow_color=str(style_cfg.get("glow_color", "8A2BE2")),
        glow_strength=int(style_cfg.get("glow_strength", 3)),
        highlight_color=str(style_cfg.get("highlight_color", "39FF14")),
    )
