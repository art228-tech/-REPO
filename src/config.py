"""Конфигурация приложения с сохранением в config.json рядом с софтом."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import paths


@dataclass
class SubtitleSettings:
    """Настройки субтитров. Всё считается ОТНОСИТЕЛЬНО исходного проекта.

    vertical_offset_percent: сдвиг по вертикали в % от высоты кадра.
        Положительное значение — ниже, отрицательное — выше. 0 = как в проекте.
    scale_percent: масштаб относительно исходного. 100 = как в проекте.
    """

    # Позиция/масштаб считаются ОТНОСИТЕЛЬНО исходного проекта (шаблона).
    # 0 % и 100 % = ровно как в проекте (ничего не двигаем).
    vertical_offset_percent: float = 0.0
    scale_percent: float = 100.0
    # Три шрифта, все начинаются на «Блок…». Софт выбирает случайный из доступных.
    font_prefix: str = "Блок"
    # Позицию/масштаб надёжнее применять правкой draft-файла (а не мышью в CapCut).
    # Для этого после генерации субтитров CapCut закрывается, правится JSON и
    # открывается снова. Если мешает — можно выключить (тогда позиция как у шаблона).
    apply_layout_via_json: bool = True
    # Стиль без чёрных краёв (белый) и шаблон — фиксируются из исходного проекта
    # автоматически при первом запуске, отдельных названий у них нет.
    # Зафиксированный шаблон субтитров из исходного проекта (id и базовые значения).
    template_id: str = ""
    captured_scale: float = 0.0        # 0 = ещё не зафиксировано
    captured_transform_y: float = 0.0


@dataclass
class ExportSettings:
    """Настройки экспорта (по требованию — фиксированные)."""

    resolution: str = "1080p"
    fps: int = 60
    bitrate: str = "Выше"  # пункт в выпадающем списке битрейта CapCut


@dataclass
class OverlaySettings:
    """Видео-наложение в середине (видео #2)."""

    # Клип целиком должен оставаться в окне [window_start; window_end] от всей длины.
    window_start_percent: float = 40.0
    window_end_percent: float = 60.0
    # Клип НЕ обрезаем (длится 2–3 сек), только переставляем и заменяем.


@dataclass
class UiSettings:
    """UI-автоматизация CapCut (автосубтитры + экспорт через интерфейс)."""

    enabled: bool = False           # пока не откалибровано скриншотами — выключено
    capcut_exe: str = ""            # путь к CapCut.exe (пусто = найти автоматически)
    asr_language: str = "Русский"
    confidence: float = 0.80        # порог совпадения скриншотов кнопок
    default_timeout: float = 30.0   # ожидание появления элемента, сек
    # Поиск кнопок по ТЕКСТУ (OCR) — основной способ, надёжнее картинок.
    # Картинки-эталоны остаются как запасной вариант.
    use_ocr: bool = True


@dataclass
class AppConfig:
    # Имя проекта CapCut (как в списке проектов). Папку draft находим по нему.
    capcut_project_name: str = ""
    # Путь к папке проектов CapCut (draft). Пусто = определить автоматически.
    capcut_drafts_dir: str = ""
    # Сколько роликов монтировать за один запуск.
    cycles: int = 1
    # Сквозной номер для имени экспортируемого файла (номер + дата).
    output_counter: int = 1

    subtitles: SubtitleSettings = field(default_factory=SubtitleSettings)
    export: ExportSettings = field(default_factory=ExportSettings)
    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    ui: UiSettings = field(default_factory=UiSettings)

    # ---- сериализация ----

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        return cls(
            capcut_project_name=data.get("capcut_project_name", ""),
            capcut_drafts_dir=data.get("capcut_drafts_dir", ""),
            cycles=int(data.get("cycles", 1)),
            output_counter=int(data.get("output_counter", 1)),
            subtitles=SubtitleSettings(**data.get("subtitles", {})),
            export=ExportSettings(**data.get("export", {})),
            overlay=OverlaySettings(**data.get("overlay", {})),
            ui=UiSettings(**data.get("ui", {})),
        )

    def save(self, path: Path | None = None) -> None:
        path = path or paths.config_path()
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        path = path or paths.config_path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except (json.JSONDecodeError, TypeError, ValueError):
            # Битый конфиг — начинаем с дефолтов, старый не трогаем.
            return cls()
