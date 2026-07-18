"""Работа с проектом CapCut (прямая правка draft-файлов).

Калибровано по реальному проекту пользователя: CapCut 9.0.0 (Windows), 9:16,
1080x1920. Структура таймлайна распознаётся семантически (см. layout.py).

Через правку draft-файла делается: замена медиа с сохранением свойств,
синхронизация конца под озвучку, перестановка наложения, удаление субтитров,
применение позиции/масштаба субтитров. Автосубтитры и экспорт — через интерфейс
(см. src/ui_automation).
"""

from __future__ import annotations

from pathlib import Path

from .document import DraftDocument
from .editor import DraftEditor, SubtitleBaseline
from .layout import LayoutError, TimelineLayout

__all__ = [
    "DraftDocument",
    "DraftEditor",
    "SubtitleBaseline",
    "TimelineLayout",
    "LayoutError",
    "find_project_dir",
    "default_drafts_dir",
    "draft_content_path",
]


def default_drafts_dir() -> Path:
    r"""Стандартный каталог проектов CapCut на Windows:
    %LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft"""
    import os

    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
    return Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"


def find_project_dir(project_name: str, drafts_dir: Path | None = None) -> Path:
    """Находит папку проекта по имени. Если имя не задано или не найдено —
    берёт самый недавно изменённый проект."""
    base = Path(drafts_dir) if drafts_dir else default_drafts_dir()
    if not base.exists():
        raise FileNotFoundError(f"Каталог проектов CapCut не найден: {base}")

    candidates = [p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")]
    if not candidates:
        raise FileNotFoundError(f"В каталоге нет проектов: {base}")

    if project_name:
        exact = base / project_name
        if exact.is_dir():
            return exact
        for p in candidates:
            if p.name.lower() == project_name.lower():
                return p

    # Фолбэк — самый свежий проект (по времени изменения draft_content.json).
    def mtime(p: Path) -> float:
        dc = p / "draft_content.json"
        return dc.stat().st_mtime if dc.exists() else p.stat().st_mtime

    latest = max(candidates, key=mtime)
    return latest


def draft_content_path(project_dir: Path) -> Path:
    """Путь к основному файлу проекта (учитывая вложенную папку Timelines)."""
    project_dir = Path(project_dir)
    root = project_dir / "draft_content.json"
    if root.exists():
        return root
    # В новых версиях основной контент бывает во вложенной папке Timelines/<uuid>/.
    timelines = project_dir / "Timelines"
    if timelines.exists():
        for sub in timelines.iterdir():
            dc = sub / "draft_content.json"
            if dc.exists():
                return dc
    return root
