"""Разбор аргументов в setup.ps1.

Строка, которая решает, что запускать, ломалась молча и одинаково для всех
команд: PowerShell разворачивает массив из одного элемента в строку, и вместо
`gui` в программу уходило три аргумента — `g`, `u`, `i`. Двойной щелчок по
run.bat заканчивался ошибкой разбора аргументов, `run.bat doctor` — тоже.

Проверять это на глаз бесполезно: в самом PowerShell строка выглядит правильно,
разница видна только по типу значения. Поэтому строка берётся прямо из
setup.ps1 и выполняется по-настоящему.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

SETUP = Path(__file__).resolve().parent.parent / "setup.ps1"

# Якорь: именно эта строка решает, что запускать. Пропадёт или изменит вид —
# тест упадёт, а не станет молча проверять пустоту.
LINE = re.compile(r"^\[string\[\]\]\$command\s*=.*$", re.MULTILINE)

pwsh = shutil.which("pwsh") or shutil.which("powershell")
needs_pwsh = pytest.mark.skipif(pwsh is None, reason="нужен PowerShell")


def _line() -> str:
    found = LINE.search(SETUP.read_text(encoding="utf-8-sig"))
    assert found is not None, (
        "В setup.ps1 не нашлась строка «[string[]]$command = ...». "
        "Если её переписали — проверьте, что массив не разворачивается в строку."
    )
    return found.group(0)


def _run(tmp_path: Path, *args: str) -> list[str]:
    """Выполняет строку из setup.ps1 и возвращает то, что уйдёт в программу.

    Через `-File`, а не `-Command`: run.bat запускает скрипт именно так, и
    только при таком запуске аргументы попадают в `$args` — ради них всё и
    затевалось.
    """
    script = tmp_path / "проба.ps1"
    script.write_text(_line() + "\n$command -join '|'\n", encoding="utf-8")

    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(script), *args],
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().split("|")


@needs_pwsh
def test_double_click_starts_the_window(tmp_path: Path):
    """Без аргументов — окно программы, а не три аргумента по букве."""
    assert _run(tmp_path) == ["gui"]


@needs_pwsh
def test_doctor_arrives_whole(tmp_path: Path):
    """Ломалось так же: до программы доезжала одна буква «d»."""
    assert _run(tmp_path, "doctor") == ["doctor"]


@needs_pwsh
def test_extra_keys_are_passed_along(tmp_path: Path):
    assert _run(tmp_path, "headless", "-v") == ["headless", "-v"]


@needs_pwsh
def test_setup_script_parses():
    """Опечатку в PowerShell больше нечем поймать: он не проверяется ничем.

    Ошибка разбора вылезла бы только на компьютере пользователя, при установке,
    и выглядела бы как «программа не ставится».
    """
    check = (
        "$errors = $null; "
        f"$null = [System.Management.Automation.Language.Parser]::ParseFile('{SETUP}', "
        "[ref]$null, [ref]$errors); "
        "if ($errors.Count) { $errors | ForEach-Object { $_.Message }; exit 1 }"
    )
    result = subprocess.run([pwsh, "-NoProfile", "-Command", check],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_window_failure_does_not_end_in_silence():
    """pythonw не показывает ошибок: упавший запуск обязан повториться с консолью."""
    body = SETUP.read_text(encoding="utf-8-sig")

    assert "HasExited" in body
    assert "pythonw.exe" in body


def test_the_array_type_is_still_forced():
    """Уберут [string[]] — и всё вернётся к запуску по буквам."""
    assert "[string[]]$command" in SETUP.read_text(encoding="utf-8-sig")


def test_setup_stays_readable_on_windows():
    """Без BOM PowerShell 5.1 читает файл как ANSI и печатает русский мусором."""
    assert SETUP.read_bytes().startswith(b"\xef\xbb\xbf")


def test_setup_keeps_windows_line_endings():
    assert b"\r\n" in SETUP.read_bytes()
