"""Отбор готовых озвучек по длительности.

Границы задаются в настройках двумя числами, и работают они независимо: можно
отсеивать только слишком короткие записи, только слишком длинные или и те и
другие сразу. Ноль означает, что с этой стороны предела нет.

Здесь же живёт разбор готовой папки: длительность будущей озвучки заранее не
известна никому, поэтому отбирать приходится по факту — либо сразу после
склейки, либо потом по всей папке.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from . import audio as audio_utils
from .errors import Cancelled
from .logging_setup import get_logger

log = get_logger("duration")

#: Расширения, у которых программа умеет измерять длительность своими силами.
#: Для остальных форматов нужен ffmpeg, и отбор по ним не работает.
MEASURABLE_SUFFIXES = (".mp3",)

ScanProgress = Callable[[int, int, str], None]


def duration_problem(seconds: Optional[float], minimum: float, maximum: float) -> str:
    """Чем готовая запись не укладывается в заданные границы.

    Пустая строка означает, что запись подходит. Неизмеренная длительность
    претензией не считается: файл, о котором ничего не известно, не удаляем.
    """
    if seconds is None:
        return ""
    if minimum and seconds < minimum:
        return f"короче {minimum:g} с"
    if maximum and seconds > maximum:
        return f"длиннее {maximum:g} с"
    return ""


@dataclass
class Measured:
    """Один проверенный файл."""

    path: Path
    seconds: Optional[float] = None
    problem: str = ""
    error: str = ""

    def line(self) -> str:
        length = audio_utils.format_duration(self.seconds) or "?"
        if self.error:
            return f"{self.path.name} — измерить не удалось: {self.error}"
        if self.problem:
            return f"{self.path.name} — {length} ({self.seconds:.1f} с), {self.problem}"
        return f"{self.path.name} — {length}"


@dataclass
class Scan:
    """Результат разбора папки."""

    folder: Path
    minimum: float = 0.0
    maximum: float = 0.0
    fitting: List[Measured] = field(default_factory=list)
    rejected: List[Measured] = field(default_factory=list)
    unmeasured: List[Measured] = field(default_factory=list)

    @property
    def checked(self) -> int:
        return len(self.fitting) + len(self.rejected) + len(self.unmeasured)

    @property
    def too_short(self) -> int:
        return sum(1 for item in self.rejected if item.problem.startswith("короче"))

    @property
    def too_long(self) -> int:
        return sum(1 for item in self.rejected if item.problem.startswith("длиннее"))


def audio_files(folder: Path) -> List[Path]:
    """Готовые озвучки, лежащие прямо в папке.

    Вглубь не идём и служебное не берём: в `_chunks` лежат куски, из которых
    склеен готовый файл, в `_voices` — превью голосов. И то и другое тоже mp3,
    но к отбору по хронометражу отношения не имеет.
    """
    if not folder.is_dir():
        return []

    files = [
        path
        for path in folder.iterdir()
        if path.is_file()
        and not path.name.startswith("_")
        and path.suffix.lower() in MEASURABLE_SUFFIXES
    ]
    return sorted(files, key=lambda p: p.name.lower())


def measure(path: Path) -> Measured:
    """Измерить длительность одного файла."""
    try:
        seconds = audio_utils.mp3_duration(path.read_bytes())
    except OSError as exc:
        return Measured(path=path, error=str(exc))

    if seconds is None:
        return Measured(path=path, error="в файле не нашлось звука")
    return Measured(path=path, seconds=seconds)


def scan_folder(
    folder: Path,
    minimum: float,
    maximum: float,
    *,
    on_progress: Optional[ScanProgress] = None,
    cancel: Optional[threading.Event] = None,
) -> Scan:
    """Измерить все готовые озвучки в папке и разложить по трём кучкам.

    Ничего не удаляет: решение о удалении принимается снаружи, увидев числа.
    """
    result = Scan(folder=folder, minimum=minimum, maximum=maximum)
    files = audio_files(folder)
    total = len(files)

    for index, path in enumerate(files, start=1):
        if cancel is not None and cancel.is_set():
            raise Cancelled()

        item = measure(path)
        if item.error:
            result.unmeasured.append(item)
        else:
            item.problem = duration_problem(item.seconds, minimum, maximum)
            (result.rejected if item.problem else result.fitting).append(item)

        if on_progress:
            on_progress(index, total, path.name)

    log.info(
        "Проверено файлов в «%s»: %d, из них не по длительности %d, измерить не удалось %d",
        folder,
        total,
        len(result.rejected),
        len(result.unmeasured),
    )
    return result


def delete(items: Sequence[Measured]) -> Tuple[int, List[str]]:
    """Удалить отобранные файлы. Возвращает число удалённых и список ошибок."""
    deleted = 0
    errors: List[str] = []

    for item in items:
        try:
            item.path.unlink()
        except OSError as exc:
            errors.append(f"{item.path.name}: {exc}")
            log.warning("Не удалось удалить %s: %s", item.path.name, exc)
        else:
            deleted += 1
            log.info("Удалён %s — %s", item.path.name, item.problem or "по длительности")

    return deleted, errors
