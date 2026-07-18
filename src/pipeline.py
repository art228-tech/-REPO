"""Оркестратор автомонтажа: один цикл = один ролик; батч = несколько роликов.

Сейчас полностью работают: валидация папок, выбор/расход файлов, логирование.
Шаги правки проекта CapCut и экспорта помечены как ожидающие калибровки
(см. src/draft и src/ui_automation) — они не выполняются вслепую, а честно
сообщают в лог, что ждут примера проекта и настройки на машине пользователя.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .assets import AssetError, AssetManager
from .config import AppConfig
from .logging_setup import get_logger

logger = get_logger()

# Порядок замены изменяемых элементов на таймлайне.
REPLACE_ORDER = [
    "music_transition",   # музыка 1
    "background_intro",   # фон 1
    "background_main",    # фон 2
    "music_overlay",      # музыка 2
    "voiceover",          # озвучка (музыка 3) — задаёт длину
    "overlay_video",      # видео-наложение (видео 2)
]


@dataclass
class CycleResult:
    index: int
    ok: bool
    picked: dict[str, str] = field(default_factory=dict)
    error: str = ""


class Pipeline:
    def __init__(
        self,
        config: AppConfig,
        assets: AssetManager,
        progress_cb: Callable[[int, int], None] | None = None,
    ) -> None:
        self.config = config
        self.assets = assets
        self.progress_cb = progress_cb
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self, cycles: int) -> list[CycleResult]:
        results: list[CycleResult] = []
        logger.info("=" * 60)
        logger.info("Запуск батча: %d цикл(ов)", cycles)

        self.assets.ensure_folders()

        # Проверяем заранее, чтобы не начинать и не расходовать файлы зря.
        try:
            self.assets.validate_for_cycles(cycles)
        except AssetError as e:
            logger.error("Остановлено до старта. %s", e)
            return [CycleResult(index=1, ok=False, error=str(e))]

        for i in range(1, cycles + 1):
            if self._stop_requested:
                logger.warning("Получен запрос на остановку. Прерываю батч.")
                break
            logger.info("-" * 60)
            logger.info("Цикл %d из %d", i, cycles)
            result = self._run_one_cycle(i)
            results.append(result)
            if self.progress_cb:
                self.progress_cb(i, cycles)
            if not result.ok:
                logger.error("Цикл %d завершился с ошибкой: %s", i, result.error)
                logger.error("Останавливаю батч и сообщаю об ошибке.")
                break

        logger.info("=" * 60)
        ok_count = sum(1 for r in results if r.ok)
        logger.info("Готово. Успешно: %d, с ошибкой: %d", ok_count, len(results) - ok_count)
        return results

    def _run_one_cycle(self, index: int) -> CycleResult:
        try:
            picked = self._select_assets()
        except AssetError as e:
            return CycleResult(index=index, ok=False, error=str(e))

        # --- Шаги, ожидающие калибровки по примеру проекта CapCut ---
        logger.info("Правка проекта CapCut (замена медиа, синхронизация конца, "
                    "перестановка наложения, удаление субтитров) — ожидает примера проекта.")
        logger.info("Автосубтитры и экспорт (1080p/60fps/битрейт «Выше») — "
                    "ожидают настройки UI-автоматизации на вашей машине.")

        # Пока эти шаги не реализованы, честно помечаем цикл как незавершённый,
        # но НЕ роняем приложение — файлы уже выбраны и залогированы.
        picked_names = {k: Path(v).name for k, v in picked.items()}
        return CycleResult(
            index=index,
            ok=False,
            picked=picked_names,
            error="Шаги монтажа/экспорта ещё не активированы (нужен пример проекта "
                  "и настройка UI на вашей машине).",
        )

    def _select_assets(self) -> dict[str, Path]:
        picked: dict[str, Path] = {}
        for key in REPLACE_ORDER:
            picked[key] = self.assets.pick(key)
        return picked
