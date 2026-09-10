"""Отчёт о проблеме и журнал.

Отчёт пересылается наружу, поэтому главное здесь — чтобы вместе с журналами не
уехал токен. Опасность не теоретическая: Telegram кладёт токен прямо в адрес
запроса, и при любой ошибке сети он оказывается в журнале целиком.
"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from conftest import video_data

from videobot import logs, report
from videobot.config import Settings

TOKEN = "8123456789:AAHnbVERYSECRETvalue_0123456789abcdef"


def _settings(**kwargs) -> Settings:
    data = {"token": TOKEN, "registry_path": __file__}
    data.update(kwargs)
    return Settings(**data)


def _texts(archive: Path) -> str:
    """Всё содержимое отчёта одной строкой — так проще искать утечку."""
    with zipfile.ZipFile(archive) as zipped:
        return "\n".join(zipped.read(name).decode("utf-8") for name in zipped.namelist())


# --- вырезание токена -----------------------------------------------------

def test_token_is_cut_out_of_any_text():
    assert TOKEN not in report.scrub(f"ошибка при запросе {TOKEN}/getMe", TOKEN)


def test_token_from_a_telegram_url_is_cut_out():
    """Ровно так он и утекает: aiogram пишет в журнал полный адрес запроса."""
    line = f"POST https://api.telegram.org/bot{TOKEN}/sendDocument failed"
    assert TOKEN not in report.scrub(line, TOKEN)


def test_token_shaped_string_is_cut_even_if_it_is_not_ours():
    """Чужой токен в журнале — тоже чужой секрет, и пересылать его нельзя."""
    other = "5555555555:BBQwertyuiopasdfghjklzxcvbnm12345678"
    assert other not in report.scrub(f"второй бот {other}", TOKEN)


def test_bot_number_alone_does_not_stay_either():
    """По номеру бота находится сам бот — в отчёте он ни к чему."""
    assert "8123456789" not in report.scrub("бот 8123456789 упал", TOKEN)


def test_ordinary_text_survives_scrubbing():
    """Вырезать надо токены, а не всё подряд: отчёт должен остаться читаемым."""
    line = "Ролик auto_0906_1420_007 залит (12.3 МБ), время 14:22:01"
    assert report.scrub(line, TOKEN) == line


# --- сам отчёт ------------------------------------------------------------

def test_report_never_carries_the_token(tmp_path: Path, base):
    """Главная проверка: отчёт уходит наружу, токен — нет."""
    journals = tmp_path / "данные" / "журналы"
    journals.mkdir(parents=True)
    (journals / "2026-09-10.log").write_text(
        f"14:20:01 ERROR запрос https://api.telegram.org/bot{TOKEN}/getMe не прошёл",
        encoding="utf-8")

    archive = report.build(tmp_path, _settings(), base)

    assert TOKEN not in _texts(archive)


def _token_line(archive: Path) -> str:
    for line in _texts(archive).splitlines():
        if line.startswith("Токен"):
            return line
    raise AssertionError("В отчёте нет строки про токен")


def test_report_says_whether_the_token_is_set_at_all(tmp_path: Path, base):
    """Без этого не отличить «токен не введён» от «токен неверный»."""
    assert _token_line(report.build(tmp_path, _settings(token=""), base)).endswith("не задан")
    assert _token_line(report.build(tmp_path, _settings(), base)).endswith("задан")


def test_report_carries_the_environment(tmp_path: Path, base):
    """Первое, что спрашивают: какой Python и какая система."""
    assert "Python:" in _texts(report.build(tmp_path, _settings(), base))


def test_report_carries_recent_errors(tmp_path: Path, base):
    logs.setup(tmp_path / "данные" / "журналы")
    logs.get_logger("проба").error("не нашёлся файл реестра")

    assert "не нашёлся файл реестра" in _texts(report.build(tmp_path, _settings(), base))


def test_report_carries_the_startup_crash(tmp_path: Path, base):
    """Сбой при запуске — единственный след, когда окно не дожило до журнала."""
    journals = tmp_path / "данные" / "журналы"
    logs.crash(journals, RuntimeError("tkinter не найден"))

    assert "tkinter не найден" in _texts(report.build(tmp_path, _settings(), base))


def test_report_counts_videos_and_people(tmp_path: Path, base):
    base.add_video("ролик", "D:/a.mp4", video_data())
    base.make_admin(42)

    text = _texts(report.build(tmp_path, _settings(), base))
    assert "В очереди на заливку:1" in text
    assert "админов:           1" in text


def test_report_survives_a_broken_base(tmp_path: Path):
    """Отчёт о сбое не должен падать сам — иначе разбирать будет нечего."""
    class _Broken:
        def counts(self):
            raise RuntimeError("база не открывается")

    text = _texts(report.build(tmp_path, _settings(), _Broken()))
    assert "Сводку собрать не вышло" in text


def test_report_takes_only_the_last_journals(tmp_path: Path, base):
    """Иначе за полгода отчёт распухнет и его нельзя будет переслать."""
    journals = tmp_path / "данные" / "журналы"
    journals.mkdir(parents=True)
    for day in range(1, 21):
        (journals / f"2026-09-{day:02d}.log").write_text("строка", encoding="utf-8")

    with zipfile.ZipFile(report.build(tmp_path, _settings(), base)) as archive:
        kept = [name for name in archive.namelist() if name.startswith("журналы/")]

    assert len(kept) == report.KEEP_LOGS
    assert "журналы/2026-09-20.log" in kept


# --- журнал ---------------------------------------------------------------

def test_errors_are_kept_apart_from_the_rest(tmp_path: Path):
    """В общем потоке ошибка тонет, а нужна она именно когда всё сломалось."""
    logs.setup(tmp_path)
    log = logs.get_logger("проба")
    log.info("обычная строка")
    log.warning("подозрительно")
    log.error("сломалось")

    errors = "\n".join(logs.errors())
    assert "обычная строка" not in errors
    assert "подозрительно" in errors
    assert "сломалось" in errors


def test_journal_keeps_the_level_visible(tmp_path: Path):
    """По строке должно быть видно, ошибка это или просто сообщение."""
    logs.setup(tmp_path)
    logs.get_logger("проба").error("сломалось")

    assert "ERROR" in logs.errors()[-1]


def test_crash_file_holds_the_whole_traceback(tmp_path: Path):
    try:
        raise ValueError("внутренняя причина")
    except ValueError as error:
        where = logs.crash(tmp_path, error)

    text = where.read_text(encoding="utf-8")
    assert "внутренняя причина" in text
    assert "Traceback" in text
    assert "Python:" in text


def test_crash_file_is_written_even_without_the_folder(tmp_path: Path):
    """Сбой может случиться раньше, чем программа создаст свои папки."""
    where = logs.crash(tmp_path / "нет" / "такой" / "папки", RuntimeError("рано"))

    assert where.is_file()
    assert "рано" in where.read_text(encoding="utf-8")


def test_startup_crash_is_written_down_and_not_swallowed(tmp_path: Path, monkeypatch):
    """Ровно тот случай, когда окно не открылось и причины нигде не было."""
    from videobot import cli

    monkeypatch.setattr(cli, "_folder", lambda: tmp_path)

    def _explode(folder, args):
        raise RuntimeError("не найден tkinter")

    monkeypatch.setattr(cli, "_work", _explode)

    assert cli.main(["gui"]) == 1

    written = (tmp_path / "данные" / "журналы" / logs.CRASH_NAME).read_text(encoding="utf-8")
    assert "не найден tkinter" in written
    assert "Traceback" in written


def test_saying_something_without_stdout_does_not_crash(monkeypatch):
    """Под pythonw stdout отсутствует, и обычный print там падает сам.

    Тогда сообщение об ошибке становится ещё одной ошибкой, и причина
    теряется окончательно — так и вышло при первом запуске.
    """
    from videobot import cli

    monkeypatch.setattr("sys.stdout", None)
    cli._say("сообщение в пустоту")


def test_aiogram_errors_reach_the_journal(tmp_path: Path):
    """Половина сбоев приходит от aiogram, и терять их нельзя."""
    logs.setup(tmp_path)
    logging.getLogger("aiogram").error("Unauthorized: bot token is invalid")

    assert any("Unauthorized" in line for line in logs.errors())
