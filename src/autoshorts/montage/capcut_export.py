"""Авто-экспорт проекта CapCut через GUI (только Windows).

CapCut не умеет экспортировать headless — кнопку «Экспорт» жмут в интерфейсе.
Здесь автоматизируем это: открываем CapCut, открываем нужный проект, жмём
«Экспорт», ждём завершения и забираем файл.

Работает ТОЛЬКО на твоём Windows-ноуте (нужен установленный CapCut 8.7.0 и
пакеты из requirements-windows.txt). На Linux/сервере вызов сразу сообщит,
что среда не поддерживается, а не молча упадёт.

Подписи кнопок берутся для русского интерфейса (UI language = ru).
"""
from __future__ import annotations

import platform
import time
from pathlib import Path

from ..config import Config
from ..logging_setup import get_logger

log = get_logger("montage.capcut_export")

# Русские подписи в CapCut 8.7.0 (правятся при смене версии/языка).
RU_LABELS = {
    "export": "Экспорт",
    "export_dialog_confirm": "Экспорт",
    "done": "Готово",
}


class CapCutExportError(Exception):
    pass


def export_draft(cfg: Config, draft_dir: Path, out_path: Path) -> Path:
    """Открыть черновик в CapCut и экспортировать в out_path."""
    if platform.system() != "Windows":
        raise CapCutExportError(
            "Авто-экспорт CapCut работает только на Windows. "
            "Для теста на другой ОС используй renderer: ffmpeg."
        )
    try:
        import pyautogui  # noqa: F401
        import pygetwindow  # noqa: F401
        from pywinauto import Application
    except ImportError as exc:
        raise CapCutExportError(
            "Нет Windows-зависимостей. pip install -r requirements-windows.txt"
        ) from exc

    capcut = cfg.montage.get("capcut", {}) or {}
    timeout = int(capcut.get("export_timeout", 600))
    labels = RU_LABELS

    log.info("Открываю CapCut для проекта %s", draft_dir.name)
    # 1) Запуск/подключение к CapCut. Путь к exe можно задать в конфиге.
    exe = capcut.get("exe_path") or _guess_capcut_exe()
    app = _launch_or_connect(Application, exe)

    # 2) Открыть проект. Надёжнее всего — по имени в списке проектов;
    #    точные шаги зависят от UI и настраиваются на ноуте.
    _open_project(app, draft_dir, labels)

    # 3) Нажать «Экспорт» и подтвердить путь/параметры.
    _click_export(app, out_path, labels)

    # 4) Дождаться завершения экспорта.
    _wait_export_done(out_path, timeout)

    if not out_path.exists():
        raise CapCutExportError(f"Экспорт не создал файл: {out_path}")
    log.info("Экспорт завершён: %s", out_path)
    return out_path


def _guess_capcut_exe() -> str | None:
    import os
    for base in (os.environ.get("LOCALAPPDATA", ""),
                 os.environ.get("PROGRAMFILES", "")):
        if not base:
            continue
        cand = Path(base) / "CapCut" / "CapCut.exe"
        if cand.exists():
            return str(cand)
    return None


def _launch_or_connect(Application, exe):
    try:
        return Application(backend="uia").connect(title_re=".*CapCut.*",
                                                  timeout=5)
    except Exception:  # noqa: BLE001
        if not exe:
            raise CapCutExportError(
                "CapCut не запущен и путь к CapCut.exe не найден. "
                "Укажи montage.capcut.exe_path в config.yaml."
            )
        app = Application(backend="uia").start(exe)
        time.sleep(8)
        return app


def _open_project(app, draft_dir: Path, labels: dict) -> None:
    # Точные клики по списку проектов настраиваются на реальном UI.
    # Оставлено точкой расширения, чтобы отладить на ноуте, а не гадать.
    raise CapCutExportError(
        "Открытие проекта в UI CapCut настраивается на этапе отладки на "
        "твоём ноуте (шаги в _open_project). Черновик уже собран в "
        f"{draft_dir} — его можно открыть вручную для проверки таймлайна."
    )


def _click_export(app, out_path: Path, labels: dict) -> None:
    win = app.top_window()
    btn = win.child_window(title=labels["export"], control_type="Button")
    btn.wait("visible enabled", timeout=30)
    btn.click_input()
    time.sleep(2)
    # Здесь настраивается диалог экспорта (путь/имя/качество) под твой UI.


def _wait_export_done(out_path: Path, timeout: int) -> None:
    deadline = time.time() + timeout
    last = -1.0
    while time.time() < deadline:
        if out_path.exists():
            size = out_path.stat().st_size
            if size == last and size > 0:
                return  # размер стабилизировался — экспорт завершён
            last = size
        time.sleep(2)
    raise CapCutExportError("Экспорт не завершился за отведённое время.")
