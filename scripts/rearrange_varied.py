#!/usr/bin/env python3
"""Rearrange texts so every ~10 consecutive files span short..long lengths."""

from __future__ import annotations

from pathlib import Path

N_BUCKETS = 10


def rearrange_folder(folder_src: Path, folder_dst: Path) -> None:
    files = sorted(folder_src.glob("*.txt"))
    names = [p.name for p in files]
    texts = [p.read_text(encoding="utf-8") for p in files]
    by_len = sorted(texts, key=lambda t: (len(t.strip()), t))
    n = len(by_len)

    buckets: list[list[str]] = [[] for _ in range(N_BUCKETS)]
    for i, t in enumerate(by_len):
        b = min(N_BUCKETS - 1, i * N_BUCKETS // n)
        buckets[b].append(t)

    varied: list[str] = []
    idxs = [0] * N_BUCKETS
    round_i = 0
    while len(varied) < n:
        order = list(range(N_BUCKETS))
        order = order[round_i % N_BUCKETS :] + order[: round_i % N_BUCKETS]
        added = False
        for b in order:
            if idxs[b] < len(buckets[b]):
                varied.append(buckets[b][idxs[b]])
                idxs[b] += 1
                added = True
                if len(varied) >= n:
                    break
        if not added:
            break
        round_i += 1

    folder_dst.mkdir(parents=True, exist_ok=True)
    for name, text in zip(names, varied):
        if text and not text.endswith("\n"):
            text += "\n"
        (folder_dst / name).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    import sys

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    for folder in ("необыч", "обыч"):
        rearrange_folder(src / folder, dst / folder)
        print("done", folder)
