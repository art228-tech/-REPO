"""Оркестратор автомонтажа: один цикл = один ролик; батч = несколько роликов.

Работают: валидация папок, выбор/расход файлов, правка проекта CapCut
(замена медиа, синхронизация конца под озвучку, перестановка наложения,
удаление субтитров, фиксация шаблона субтитров), сохранение проекта.

Автосубтитры (ASR), выбор стиля/шрифта/шаблона кнопками и экспорт выполняются
через интерфейс CapCut (src/ui_automation) и подключаются на машине пользователя.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import draft
from .assets import AssetError, AssetManager
from .config import AppConfig
from .draft import DraftDocument, DraftEditor
from .draft.layout import LayoutError
from .draft.probe import ProbeError, probe_duration_us
from .logging_setup import get_logger
from .ui_automation import UiAutomationNotReadyError, UiError, run_captions_and_export

logger = get_logger()


@dataclass
class CycleResult:
    index: int
    ok: bool
    picked: dict[str, str] = field(default_factory=dict)
    edited_project: str = ""
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
                logger.error("Цикл %d остановлен: %s", i, result.error)
                logger.error("Останавливаю батч и сообщаю об ошибке.")
                break

        logger.info("=" * 60)
        ok_count = sum(1 for r in results if r.ok)
        logger.info("Готово. Успешно: %d, с ошибкой: %d", ok_count, len(results) - ok_count)
        return results

    # ---- один цикл ----

    def _run_one_cycle(self, index: int) -> CycleResult:
        try:
            picked = self._select_assets()
        except AssetError as e:
            return CycleResult(index=index, ok=False, error=str(e))

        picked_names = {k: Path(v).name for k, v in picked.items()}

        try:
            durs = {k: probe_duration_us(v) for k, v in picked.items()}
        except ProbeError as e:
            return CycleResult(index=index, ok=False, picked=picked_names, error=str(e))

        # Находим проект и правим draft-файл.
        try:
            project_dir = draft.find_project_dir(
                self.config.capcut_project_name,
                Path(self.config.capcut_drafts_dir) if self.config.capcut_drafts_dir else None,
            )
        except FileNotFoundError as e:
            return CycleResult(index=index, ok=False, picked=picked_names, error=str(e))

        dc_path = draft.draft_content_path(project_dir)
        logger.info("Проект: %s", project_dir.name)
        logger.info("Файл проекта: %s", dc_path)

        # Если включена автоматизация — CapCut мог остаться открытым и затрёт
        # нашу правку файла. Закрываем его ПЕРЕД правкой draft.
        if getattr(self.config.ui, "enabled", False):
            try:
                from .ui_automation.capcut import close_capcut_process
                close_capcut_process(self.config.ui.capcut_exe)
                logger.info("CapCut закрыт перед правкой проекта (чтобы не затёр изменения).")
            except Exception as e:  # noqa: BLE001
                logger.info("Не удалось закрыть CapCut перед правкой (возможно, не запущен): %s", e)

        try:
            doc = DraftDocument.load(dc_path)
            ed = DraftEditor(doc)
        except (OSError, ValueError, LayoutError) as e:
            return CycleResult(index=index, ok=False, picked=picked_names,
                               error=f"Не удалось разобрать проект: {e}")

        # Фиксируем шаблон субтитров один раз (пока проект в исходном виде).
        baseline = ed.capture_subtitle_baseline()
        self._persist_template(baseline)

        # Замена всех изменяемых элементов по порядку.
        ed.replace_transition_sound(str(picked["music_transition"]), durs["music_transition"])
        ed.replace_background_intro(str(picked["background_intro"]), durs["background_intro"])
        ed.replace_background_main(str(picked["background_main"]), durs["background_main"])
        ed.replace_overlay_sounds(
            str(picked["music_overlay_a"]), durs["music_overlay_a"],
            str(picked["music_overlay_b"]), durs["music_overlay_b"],
        )
        ed.replace_voiceover(str(picked["voiceover"]), durs["voiceover"])
        ed.replace_overlay_video(str(picked["overlay_video"]), durs["overlay_video"])

        # Синхронизация конца под озвучку и перестановка наложения.
        ed.sync_to_voiceover()
        ed.reposition_overlay(
            self.config.overlay.window_start_percent,
            self.config.overlay.window_end_percent,
        )
        # Ничто не должно уходить дальше конца видео (иначе чёрный фон в конце).
        ed.clamp_segments_to_total()

        # Удаляем старые субтитры (новые сгенерирует ASR в интерфейсе).
        ed.delete_subtitles()

        saved = doc.save(dc_path, backup=True)
        logger.info("Проект сохранён (резервная копия .bak рядом): %s", saved)

        # Дальше — только интерфейс CapCut (автосубтитры + экспорт).
        output_name = f"{self.config.output_counter:03d}_{datetime.now():%Y-%m-%d}"
        layout_cb = self._make_layout_callback(dc_path)
        try:
            run_captions_and_export(self.config, output_name, layout_callback=layout_cb)
        except UiAutomationNotReadyError as e:
            return CycleResult(
                index=index, ok=False, picked=picked_names, edited_project=str(dc_path),
                error=f"Правка проекта выполнена и сохранена. Остаётся интерфейсный шаг: {e}",
            )
        except UiError as e:
            return CycleResult(
                index=index, ok=False, picked=picked_names, edited_project=str(dc_path),
                error=f"Сбой UI-автоматизации: {e}",
            )

        # Успех — увеличиваем сквозной номер для имени файла.
        self.config.output_counter += 1
        try:
            self.config.save()
        except OSError:
            pass
        logger.info("Ролик готов: %s", output_name)
        return CycleResult(index=index, ok=True, picked=picked_names, edited_project=str(dc_path))

    def _select_assets(self) -> dict[str, Path]:
        keys = [
            "music_transition", "background_intro", "background_main",
            "voiceover", "overlay_video",
        ]
        picked: dict[str, Path] = {k: self.assets.pick(k) for k in keys}
        # «Музыка 2» используется дважды (перед наложением и перед фото) —
        # два независимых случайных выбора из одной папки.
        picked["music_overlay_a"] = self.assets.pick("music_overlay")
        picked["music_overlay_b"] = self.assets.pick("music_overlay")
        return picked

    def _make_layout_callback(self, dc_path):
        """Возвращает функцию, которая (пока CapCut закрыт) перечитывает проект
        с уже сгенерированными субтитрами и применяет к ним позицию/масштаб
        правкой draft-файла. Если правка через JSON выключена или проценты
        нулевые — возвращает None (тогда шаг пропускается)."""
        subs = self.config.subtitles
        if not subs.apply_layout_via_json:
            return None
        if abs(subs.vertical_offset_percent) < 1e-6 and abs(subs.scale_percent - 100.0) < 1e-6:
            logger.info("Позиция/масштаб субтитров = как в проекте — правка JSON не нужна.")
            return None

        def _apply() -> None:
            logger.info("Правлю позицию/масштаб субтитров в файле проекта…")
            doc2 = DraftDocument.load(dc_path)
            ed2 = DraftEditor(doc2)
            n = ed2.apply_subtitle_layout(
                subs.vertical_offset_percent, subs.scale_percent,
            )
            if n:
                doc2.save(dc_path, backup=False)
                logger.info("Позиция/масштаб субтитров сохранены (%d сегм.).", n)
            else:
                logger.warning("Субтитры не найдены при правке позиции/масштаба.")

        return _apply

    def _persist_template(self, baseline) -> None:
        subs = self.config.subtitles
        if not subs.template_id and baseline.template_id:
            subs.template_id = baseline.template_id
            subs.captured_scale = baseline.scale_x
            subs.captured_transform_y = baseline.transform_y
            try:
                self.config.save()
                logger.info("Зафиксирован шаблон субтитров: %s", baseline.template_id[:8])
            except OSError:
                pass
