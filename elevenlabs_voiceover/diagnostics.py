"""Сбор диагностического отчёта.

Один zip, который можно приложить к сообщению о проблеме. Ключ из отчёта
вырезается дважды: сначала не кладём его в выгрузку конфига, затем прогоняем
весь текст через ту же вырезку, что и логи.
"""

from __future__ import annotations

import json
import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from . import audio as audio_utils
from .config import Settings
from .logging_setup import get_logger, log_files, redact
from .paths import reports_dir, user_data_dir
from .state import StateStore

log = get_logger("report")

REPORT_README = """Отчёт программы «Озвучка ElevenLabs».

Что внутри:
  environment.json — версия ОС, Python и наличие ffmpeg
  settings.json    — настройки БЕЗ API-ключа
  state.json       — сводка по базе прогресса и последние ошибки
  logs/            — журналы работы

API-ключ вырезан из всех файлов автоматически. Если вы редактируете отчёт
вручную, проверьте, что ключ не попал в него повторно.
"""


def environment_info() -> Dict[str, Any]:
    ffmpeg = audio_utils.find_ffmpeg()
    return {
        "collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "app_version": "1.0",
        "python": sys.version,
        "python_executable": sys.executable,
        "frozen": bool(getattr(sys, "frozen", False)),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "data_dir": str(user_data_dir()),
        "ffmpeg": ffmpeg or "не найден",
    }


def build_report(
    settings: Settings,
    state: Optional[StateStore] = None,
    *,
    destination: Optional[Path] = None,
) -> Path:
    """Собрать zip с логами и настройками. Возвращает путь к архиву."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = destination or (reports_dir() / f"report-{stamp}.zip")
    target.parent.mkdir(parents=True, exist_ok=True)

    settings_dump = json.dumps(settings.to_dict(include_secrets=False), ensure_ascii=False, indent=2)
    environment_dump = json.dumps(environment_info(), ensure_ascii=False, indent=2)

    try:
        state_summary = (state or StateStore()).summary()
    except Exception as exc:  # noqa: BLE001 - отчёт нужен даже при битой базе
        state_summary = {"error": f"не удалось прочитать базу: {exc}"}
    state_dump = json.dumps(state_summary, ensure_ascii=False, indent=2, default=str)

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", REPORT_README)
        archive.writestr("environment.json", redact(environment_dump))
        archive.writestr("settings.json", redact(settings_dump))
        archive.writestr("state.json", redact(state_dump))

        for path in log_files():
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                archive.writestr(f"logs/{path.name}.error.txt", f"не удалось прочитать: {exc}")
                continue
            archive.writestr(f"logs/{path.name}", redact(content))

    log.info("Диагностический отчёт собран: %s", target)
    return target
