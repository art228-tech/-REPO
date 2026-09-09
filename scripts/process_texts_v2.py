#!/usr/bin/env python3
"""Process необыч/обыч with comma-before-last-sentence rule for необыч."""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

ROOT = Path("/tmp/drive_extract2")
NEO = ROOT / "необыч"
OBY = ROOT / "обыч"
REPORT_PATH = Path("/tmp/work_report2.json")

SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    return SENT_SPLIT.split(text)


def remove_last_sentence(text: str) -> tuple[str, str]:
    parts = split_sentences(text)
    if len(parts) <= 1:
        return text.strip(), ""
    return " ".join(parts[:-1]), parts[-1]


def append_sentence(text: str, sentence: str) -> str:
    text = text.strip()
    sentence = sentence.strip()
    if not sentence:
        return text
    if not text:
        return sentence
    return f"{text} {sentence}"


def replace_sentence_periods(text: str) -> str:
    return re.sub(r"\.(?=\s|$)", "!", text)


def bang_to_comma_before_last(text: str) -> str:
    """In необыч: replace '!' immediately before the last sentence with ','."""
    parts = split_sentences(text)
    if len(parts) < 2:
        return text.strip()
    # Rejoin all but last with '! ' (they already end without delimiter in split),
    # but split_sentences strips delimiters — reconstruct carefully.
    # Better: find the last sentence start and change preceding '!'.
    stripped = text.strip()
    last = parts[-1]
    # Find last occurrence of last sentence
    idx = stripped.rfind(last)
    if idx <= 0:
        return stripped
    before = stripped[:idx].rstrip()
    if before.endswith("!"):
        before = before[:-1] + ","
        # ensure single space before last sentence
        return f"{before} {last}"
    return stripped


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    if text and not text.endswith("\n"):
        text = text + "\n"
    path.write_text(text, encoding="utf-8")


def avg_chars(folder: Path) -> dict:
    lengths = [len(read_text(p).strip()) for p in folder.glob("*.txt")]
    return {
        "count": len(lengths),
        "avg_chars": round(statistics.mean(lengths), 4),
        "min": min(lengths),
        "max": max(lengths),
        "median": statistics.median(lengths),
    }


def main() -> None:
    neo_files = list(NEO.glob("*.txt"))
    oby_files = list(OBY.glob("*.txt"))
    assert len(neo_files) == 50000, len(neo_files)
    assert len(oby_files) == 50000, len(oby_files)

    neo_ranked = sorted(neo_files, key=lambda p: (-len(read_text(p)), p.name))
    oby_ranked = sorted(oby_files, key=lambda p: (len(read_text(p)), p.name))

    longest_half = neo_ranked[:25000]
    shortest_half = oby_ranked[:25000]

    removed_sentences: list[str] = []
    processed_long: list[tuple[str, str]] = []
    processed_short: list[tuple[str, str]] = []

    for long_path, short_path in zip(longest_half, shortest_half):
        without_last, last = remove_last_sentence(read_text(long_path))
        removed_sentences.append(last)
        short_new = append_sentence(read_text(short_path), last)
        processed_long.append((long_path.name, without_last))
        processed_short.append((short_path.name, short_new))

    # Swap halves between folders
    for (long_name, long_content), (short_name, short_content) in zip(
        processed_long, processed_short
    ):
        write_text(OBY / short_name, long_content)
        write_text(NEO / long_name, short_content)

    # Replace sentence-final '.' with '!' in ALL files
    for folder in (NEO, OBY):
        for path in folder.glob("*.txt"):
            write_text(path, replace_sentence_periods(read_text(path)))

    # NEW: in необыч only — '!' before last sentence → ','
    comma_changed = 0
    for path in NEO.glob("*.txt"):
        original = read_text(path)
        updated = bang_to_comma_before_last(original)
        if updated.strip() != original.strip():
            comma_changed += 1
        write_text(path, updated)

    neo_stats = avg_chars(NEO)
    oby_stats = avg_chars(OBY)

    report = {
        "sentences_removed": len(removed_sentences),
        "empty_removed": sum(1 for s in removed_sentences if not s),
        "neobych_comma_before_last_changed": comma_changed,
        "neobych_avg_chars": neo_stats,
        "obych_avg_chars": oby_stats,
        "sample_neobych": read_text(NEO / longest_half[0].name)[:400],
        "sample_obych": read_text(OBY / shortest_half[0].name)[:400],
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
