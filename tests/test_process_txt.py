#!/usr/bin/env python3
"""Spec tests for process_txt.bat: natural sort, skip, cycle, append, backup, restore."""
from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path


LOG_SKIP = re.compile(r"^_(process|restore)_log_")


def natural_key(name: str) -> tuple:
    parts: list = []
    pos = 0
    for m in re.finditer(r"\d+", name):
        if m.start() > pos:
            parts.append(name[pos : m.start()].lower())
        parts.append(int(m.group()))
        pos = m.end()
    if pos < len(name):
        parts.append(name[pos:].lower())
    return tuple(parts)


def target_txt_files(folder: Path) -> list[Path]:
    files = [
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() == ".txt" and not LOG_SKIP.match(p.name)
    ]
    return sorted(files, key=lambda p: (natural_key(p.name), p.name))


def add_last_sentence(text: str, sentence: str) -> str:
    had_crlf = text.endswith("\r\n")
    had_lf = (not had_crlf) and text.endswith("\n")
    had_cr = (not had_crlf) and (not had_lf) and text.endswith("\r")
    core = re.sub(r"[\s]+$", "", text)
    result = sentence if core == "" else f"{core} {sentence}"
    if had_crlf:
        result += "\r\n"
    elif had_lf:
        result += "\n"
    elif had_cr:
        result += "\r"
    return result


def process_folder(folder: Path, skip: int, sentences: list[str]) -> dict:
    files = target_txt_files(folder)
    to_skip = min(skip, len(files))
    work = files[to_skip:]
    backup = folder / "_txt_backup"
    backup.mkdir(exist_ok=True)
    ok = 0
    log_lines = []
    for i, path in enumerate(work):
        sentence = sentences[i % len(sentences)]
        bak = backup / path.name
        if not bak.exists():
            shutil.copy2(path, bak)
        original = path.read_text(encoding="utf-8")
        path.write_text(add_last_sentence(original, sentence), encoding="utf-8")
        log_lines.append(f"[OK]   {path.name}  ->  {sentence}")
        ok += 1
    log_path = folder / "_process_log_test.txt"
    log_path.write_text("\n".join(log_lines) + f"\nИтого: успешно {ok}\n", encoding="utf-8")
    return {"total": len(files), "skipped": to_skip, "processed": ok, "work": work}


def restore_folder(folder: Path) -> int:
    backup = folder / "_txt_backup"
    n = 0
    for bak in backup.glob("*.txt"):
        shutil.copy2(bak, folder / bak.name)
        n += 1
    log_path = folder / "_restore_log_test.txt"
    log_path.write_text(f"восстановлено {n}\n", encoding="utf-8")
    return n


class NaturalSortTests(unittest.TestCase):
    def test_numeric_order(self):
        names = ["10.txt", "2.txt", "1.txt", "9.txt"]
        ordered = sorted(names, key=natural_key)
        self.assertEqual(ordered, ["1.txt", "2.txt", "9.txt", "10.txt"])

    def test_prefixed_numbers(self):
        names = ["text_100.txt", "text_20.txt", "text_3.txt"]
        ordered = sorted(names, key=natural_key)
        self.assertEqual(ordered, ["text_3.txt", "text_20.txt", "text_100.txt"])


class AppendTests(unittest.TestCase):
    def test_appends_with_space(self):
        self.assertEqual(add_last_sentence("Привет мир.", "Конец."), "Привет мир. Конец.")

    def test_empty_file(self):
        self.assertEqual(add_last_sentence("", "Одно."), "Одно.")

    def test_keeps_trailing_newline(self):
        self.assertEqual(add_last_sentence("Текст.\n", "Хвост."), "Текст. Хвост.\n")

    def test_keeps_crlf(self):
        self.assertEqual(add_last_sentence("Текст.\r\n", "Хвост."), "Текст. Хвост.\r\n")


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # 275 files: 1.txt .. 275.txt
        for i in range(1, 276):
            (self.tmp / f"{i}.txt").write_text(f"файл {i}", encoding="utf-8")
        (self.tmp / "_process_log_old.txt").write_text("ignore me", encoding="utf-8")

    def test_skips_first_270_and_cycles(self):
        sentences = ["Альфа.", "Бета.", "Гамма."]
        result = process_folder(self.tmp, skip=270, sentences=sentences)
        self.assertEqual(result["total"], 275)  # log file excluded
        self.assertEqual(result["skipped"], 270)
        self.assertEqual(result["processed"], 5)

        self.assertEqual((self.tmp / "270.txt").read_text(encoding="utf-8"), "файл 270")
        self.assertEqual((self.tmp / "271.txt").read_text(encoding="utf-8"), "файл 271 Альфа.")
        self.assertEqual((self.tmp / "272.txt").read_text(encoding="utf-8"), "файл 272 Бета.")
        self.assertEqual((self.tmp / "273.txt").read_text(encoding="utf-8"), "файл 273 Гамма.")
        self.assertEqual((self.tmp / "274.txt").read_text(encoding="utf-8"), "файл 274 Альфа.")
        self.assertEqual((self.tmp / "275.txt").read_text(encoding="utf-8"), "файл 275 Бета.")

        log = (self.tmp / "_process_log_test.txt").read_text(encoding="utf-8")
        self.assertIn("[OK]   271.txt  ->  Альфа.", log)
        self.assertIn("Итого: успешно 5", log)

    def test_backup_keeps_first_original_and_restore(self):
        sentences = ["Раз.", "Два."]
        process_folder(self.tmp, skip=270, sentences=sentences)
        original_271 = (self.tmp / "_txt_backup" / "271.txt").read_text(encoding="utf-8")
        self.assertEqual(original_271, "файл 271")

        process_folder(self.tmp, skip=270, sentences=["Ещё."])
        # backup must still be the first original
        self.assertEqual((self.tmp / "_txt_backup" / "271.txt").read_text(encoding="utf-8"), "файл 271")
        self.assertEqual((self.tmp / "271.txt").read_text(encoding="utf-8"), "файл 271 Раз. Ещё.")

        n = restore_folder(self.tmp)
        self.assertEqual(n, 5)
        self.assertEqual((self.tmp / "271.txt").read_text(encoding="utf-8"), "файл 271")
        self.assertEqual((self.tmp / "1.txt").read_text(encoding="utf-8"), "файл 1")
        self.assertTrue((self.tmp / "_restore_log_test.txt").exists())


if __name__ == "__main__":
    unittest.main()
