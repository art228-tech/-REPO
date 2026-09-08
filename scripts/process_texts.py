#!/usr/bin/env python3
"""Process необыч/обыч text folders per task rules."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path("/tmp/drive_extract")
NEO = ROOT / "необыч"
OBY = ROOT / "обыч"
REPORT_PATH = Path("/tmp/work_report.json")

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
    last = parts[-1]
    rest = " ".join(parts[:-1])
    return rest, last


def append_sentence(text: str, sentence: str) -> str:
    text = text.strip()
    sentence = sentence.strip()
    if not sentence:
        return text
    if not text:
        return sentence
    return f"{text} {sentence}"


def replace_sentence_periods(text: str) -> str:
    """Replace sentence-ending periods with exclamation marks."""
    # All '.' that terminate a sentence (before whitespace/EOL or EOF).
    return re.sub(r"\.(?=\s|$)", "!", text)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    if text and not text.endswith("\n"):
        text = text + "\n"
    path.write_text(text, encoding="utf-8")


def main() -> None:
    neo_files = list(NEO.glob("*.txt"))
    oby_files = list(OBY.glob("*.txt"))
    assert len(neo_files) == 50000, len(neo_files)
    assert len(oby_files) == 50000, len(oby_files)

    # Rank by character length (content), tie-break by name for stability.
    neo_ranked = sorted(
        neo_files, key=lambda p: (-len(read_text(p)), p.name)
    )
    oby_ranked = sorted(
        oby_files, key=lambda p: (len(read_text(p)), p.name)
    )

    longest_half = neo_ranked[:25000]
    shortest_half = oby_ranked[:25000]

    removed_sentences: list[str] = []
    processed_long: list[tuple[str, str]] = []  # (filename, new_content)
    processed_short: list[tuple[str, str]] = []

    for long_path, short_path in zip(longest_half, shortest_half):
        long_text = read_text(long_path)
        short_text = read_text(short_path)

        without_last, last = remove_last_sentence(long_text)
        removed_sentences.append(last)
        short_new = append_sentence(short_text, last)

        processed_long.append((long_path.name, without_last))
        processed_short.append((short_path.name, short_new))

    # Swap halves between folders:
    # processed longest (from необыч) -> обыч (slot of paired shortest name)
    # processed shortest (from обыч) -> необыч (slot of paired longest name)
    for (long_name, long_content), (short_name, short_content) in zip(
        processed_long, processed_short
    ):
        write_text(OBY / short_name, long_content)
        write_text(NEO / long_name, short_content)

    # Replace '.' at end of every sentence with '!' in ALL files.
    bang_neo = bang_oby = 0
    for folder in (NEO, OBY):
        for path in folder.glob("*.txt"):
            original = read_text(path)
            updated = replace_sentence_periods(original)
            if updated != original:
                write_text(path, updated)
                if folder is NEO:
                    bang_neo += 1
                else:
                    bang_oby += 1
            elif not original.endswith("\n"):
                write_text(path, original)

    # Verification samples
    empty_removed = sum(1 for s in removed_sentences if not s)
    report = {
        "neobych_total": 50000,
        "obych_total": 50000,
        "longest_half_count": 25000,
        "shortest_half_count": 25000,
        "sentences_removed": len(removed_sentences),
        "empty_removed_sentence_count": empty_removed,
        "files_with_period_replacements_neobych": bang_neo,
        "files_with_period_replacements_obych": bang_oby,
        "longest_half_name_sample": [p.name for p in longest_half[:5]],
        "shortest_half_name_sample": [p.name for p in shortest_half[:5]],
        "removed_sentence_sample": removed_sentences[:5],
        "pairing": "rank i: i-th longest необыч <-> i-th shortest обыч",
        "swap_rule": (
            "после обработки: контент longest -> обыч/<short_name>; "
            "контент shortest -> необыч/<long_name>"
        ),
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
