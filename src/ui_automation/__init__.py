"""UI-автоматизация CapCut (Windows): автосубтитры + экспорт.

Часть шагов невозможно сделать правкой draft-файлов — только через интерфейс:
  * генерация автосубтитров (распознавание речи — онлайн-функция CapCut);
  * применение стиля субтитров без чёрных краёв, шаблона и шрифта «Блок»;
  * экспорт (1080p / 60fps / битрейт «Выше») в папку «Результат».

Реализовано на кликах по эталонным скриншотам кнопок (см. capcut.py). Требует
калибровки на машине пользователя: нужно один раз положить скриншоты кнопок в
папку «Интерфейс (скриншоты кнопок)». Пока их нет или UI выключен в настройках —
поднимается UiAutomationNotReadyError, а правка проекта уже выполнена и сохранена.
"""

from __future__ import annotations

import random

from .framework import UiError

__all__ = ["UiError", "UiAutomationNotReadyError", "run_captions_and_export"]


class UiAutomationNotReadyError(Exception):
    """UI-автоматизация выключена или не хватает скриншотов кнопок."""


def run_captions_and_export(config, output_filename: str) -> None:
    """Полный интерфейсный цикл: открыть проект → автосубтитры → стиль/шрифт/
    шаблон → сохранить → экспорт. Бросает UiAutomationNotReadyError, если UI
    выключен или не готовы скриншоты."""
    from .. import paths
    from .capcut import CapCutController, ensure_references, missing_references
    from .framework import Screen

    if not getattr(config, "ui", None) or not config.ui.enabled:
        raise UiAutomationNotReadyError(
            "UI-автоматизация выключена. Включите её в «Настройках»."
        )

    refs = paths.references_dir()
    defaults = paths.reference_defaults_dir()
    # Встроенные эталоны копируем пользователю (работает из коробки, можно заменить).
    ensure_references(refs, defaults)
    missing = missing_references(refs, defaults)
    if missing:
        raise UiAutomationNotReadyError(
            "Не хватает эталонов кнопок: " + ", ".join(missing)
        )

    screen = Screen(
        references_dir=refs,
        shots_dir=paths.ui_shots_dir(),
        confidence=config.ui.confidence,
        default_timeout=config.ui.default_timeout,
        defaults_dir=defaults,
    )
    ctrl = CapCutController(screen, config.ui.capcut_exe)
    ctrl.open_project(config.capcut_project_name)
    ctrl.generate_captions()
    ctrl.apply_caption_style(random.Random())
    ctrl.save_project()
    ctrl.export(
        output_filename,
        config.export.resolution,
        config.export.fps,
        config.export.bitrate,
    )
