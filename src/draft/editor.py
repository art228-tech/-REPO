"""Высокоуровневые операции монтажа над проектом CapCut (правка draft-файла).

Реализует всё, что можно сделать без интерфейса CapCut:
  * замена медиа с сохранением скорости/громкости/эффектов («Заменить»);
  * замена озвучки и синхронизация конца ролика под неё (обрезка/удлинение
    фона и фоновой музыки);
  * перестановка видео-наложения в случайную позицию в окне 40–60% длины;
  * удаление существующих субтитров (перед генерацией новых);
  * применение стиля субтитров (позиция/масштаб) к уже сгенерированным.

Генерация автосубтитров, выбор стиля/шрифта/шаблона кнопками и экспорт —
делаются через интерфейс (см. src/ui_automation).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from ..logging_setup import get_logger
from .document import DraftDocument
from .layout import TimelineLayout

logger = get_logger()


def _speed(seg: dict) -> float:
    return float(seg.get("speed", 1.0) or 1.0)


def _set_target(seg: dict, start: int, dur: int) -> None:
    seg["target_timerange"] = {"start": int(round(start)), "duration": int(round(dur))}


def _set_source(seg: dict, start: int, dur: int) -> None:
    seg["source_timerange"] = {"start": int(round(start)), "duration": int(round(dur))}


def _target(seg: dict) -> tuple[int, int]:
    tr = seg.get("target_timerange", {})
    return int(tr.get("start", 0)), int(tr.get("duration", 0))


@dataclass
class SubtitleBaseline:
    """Снимок оформления субтитров из исходного проекта (шаблон/шрифт/позиция)."""

    template_id: str = ""
    template_resource_id: str = ""
    font_name: str = ""
    font_id: str = ""
    style_name: str = ""
    scale_x: float = 1.0
    scale_y: float = 1.0
    transform_y: float = 0.0
    transform_x: float = 0.0


class DraftEditor:
    def __init__(self, doc: DraftDocument) -> None:
        self.doc = doc
        self.layout = TimelineLayout(doc)

    # ---------------- замена медиа ----------------

    def _replace_media(self, seg: dict, new_path: str, new_dur_us: int) -> None:
        """Меняет материал сегмента на новый файл, сохраняя все свойства сегмента
        (скорость/громкость/эффекты/трансформ). Аналог «Заменить» в CapCut."""
        cur_id = seg.get("material_id", "")
        found = self.doc.material(cur_id)
        if not found:
            raise KeyError(f"Материал сегмента не найден: {cur_id}")
        category, _ = found
        name = new_path.replace("\\", "/").split("/")[-1]
        new_id = self.doc.clone_material_from(cur_id, {
            "path": new_path,
            "material_name": name,
            "name": name,
            "duration": int(new_dur_us),
        })
        seg["material_id"] = new_id
        # Источник: с начала нового файла, длиной под текущий кадр таймлайна.
        _, tgt_dur = _target(seg)
        want_src = int(round(tgt_dur * _speed(seg)))
        if want_src > new_dur_us:
            logger.warning(
                "Файл %s короче требуемого (%.2fs < %.2fs) — источник обрезан.",
                name, new_dur_us / 1e6, want_src / 1e6,
            )
            want_src = new_dur_us
        _set_source(seg, 0, want_src)

    def replace_background_intro(self, path: str, dur_us: int) -> None:
        for seg in self.layout.bg_intro_segments:
            self._replace_media(seg, path, dur_us)
        logger.info("Заменён вступительный фон (2 слоя): %s", path)

    def replace_background_main(self, path: str, dur_us: int) -> None:
        self._bg_main_path = path
        self._bg_main_dur = dur_us
        for seg in self.layout.bg_main_segments:
            self._replace_media(seg, path, dur_us)
        logger.info("Заменён основной фон (2 слоя): %s", path)

    def replace_transition_sound(self, path: str, dur_us: int) -> None:
        self._replace_media(self.layout.transition_sfx_segment, path, dur_us)
        logger.info("Заменён звук перехода: %s", path)

    def replace_overlay_sounds(self, path_before_overlay: str, dur1: int,
                               path_before_photo: str, dur2: int) -> None:
        self._replace_media(self.layout.pre_overlay_sfx_segment, path_before_overlay, dur1)
        self._replace_media(self.layout.pre_photo_sfx_segment, path_before_photo, dur2)
        logger.info("Заменены звуки «Музыка 2» (перед наложением и перед фото).")

    def replace_overlay_video(self, path: str, dur_us: int) -> None:
        # Наложение не режем — сохраняем длину кадра как есть, только меняем файл.
        self._replace_media(self.layout.overlay_video_segment, path, dur_us)
        logger.info("Заменено видео-наложение: %s", path)

    def replace_voiceover(self, path: str, dur_us: int) -> None:
        """Заменяет озвучку и делает её длину эталонной для всего ролика."""
        seg = self.layout.voiceover_segment
        cur_id = seg.get("material_id", "")
        name = path.replace("\\", "/").split("/")[-1]
        new_id = self.doc.clone_material_from(cur_id, {
            "path": path, "material_name": name, "name": name, "duration": int(dur_us),
        })
        seg["material_id"] = new_id
        _set_target(seg, 0, dur_us)
        _set_source(seg, 0, int(round(dur_us * _speed(seg))))
        logger.info("Заменена озвучка: %s (%.2fs) — задаёт длину ролика.", name, dur_us / 1e6)

    # ---------------- синхронизация конца ----------------

    def sync_to_voiceover(self) -> int:
        """Подгоняет фон, фоновую музыку и концовку (фото + звук) под длину озвучки.
        Возвращает итоговую длину ролика V (мкс)."""
        _, v_dur = _target(self.layout.voiceover_segment)
        V = int(v_dur)

        # Вступительный фон фиксирован; основной фон тянется до конца.
        intro_end = max(self._seg_end(s) for s in self.layout.bg_intro_segments)
        for seg in self.layout.bg_main_segments:
            self._resize_video_to(seg, intro_end, V - intro_end)

        # Фоновая музыка на весь ролик.
        self._resize_audio_to(self.layout.bgmusic_segment, 0, V)

        # Концовка: фото прижато к концу, звук перед фото — со своим смещением.
        photo = self.layout.photo_segment
        pre_photo = self.layout.pre_photo_sfx_segment
        _, photo_dur = _target(photo)
        p_start_old, _ = _target(photo)
        sfx_start_old, sfx_dur = _target(pre_photo)
        delta = sfx_start_old - p_start_old
        new_photo_start = V - photo_dur
        _set_target(photo, new_photo_start, photo_dur)
        _set_target(pre_photo, new_photo_start + delta, sfx_dur)

        self.doc.total_duration = V
        logger.info("Синхронизировано под озвучку: длина ролика %.2fs.", V / 1e6)
        return V

    def clamp_segments_to_total(self) -> None:
        """Обрезает хвосты всех сегментов, выходящие за конец ролика, чтобы
        ничего не уходило дальше видео (иначе в конце появляется чёрный фон)."""
        V = self.doc.total_duration
        for track in self.doc.tracks:
            for seg in track.get("segments", []):
                s, d = _target(seg)
                end = s + d
                if end <= V:
                    continue
                new_d = V - s
                if new_d <= 0:
                    logger.warning("Сегмент начинается за концом ролика — пропускаю.")
                    continue
                _set_target(seg, s, new_d)
                src = seg.get("source_timerange")
                if src is not None:
                    _set_source(seg, int(src.get("start", 0)),
                                int(round(new_d * _speed(seg))))
                logger.info("Обрезан хвост за концом ролика: -%.2fs", (end - V) / 1e6)

    def _resize_video_to(self, seg: dict, start: int, dur: int) -> None:
        """Растягивает/обрезает видео-сегмент до нужной длины (по требованию —
        «просто удлинить/расширить ролик»)."""
        _set_target(seg, start, dur)
        want_src = int(round(dur * _speed(seg)))
        obj = self.doc.material_obj(seg.get("material_id", ""))
        mat_dur = int(obj.get("duration", 0)) if obj else 0
        if mat_dur and want_src > mat_dur:
            logger.warning(
                "Фон короче нужного (%.2fs < %.2fs) — источник ограничен длиной файла.",
                mat_dur / 1e6, want_src / 1e6,
            )
            want_src = mat_dur
        _set_source(seg, 0, want_src)

    def _resize_audio_to(self, seg: dict, start: int, dur: int) -> None:
        _set_target(seg, start, dur)
        want_src = int(round(dur * _speed(seg)))
        obj = self.doc.material_obj(seg.get("material_id", ""))
        mat_dur = int(obj.get("duration", 0)) if obj else 0
        src_start = int(seg.get("source_timerange", {}).get("start", 0))
        if mat_dur and src_start + want_src > mat_dur:
            want_src = max(0, mat_dur - src_start)
        _set_source(seg, src_start, want_src)

    # ---------------- перестановка наложения ----------------

    def reposition_overlay(self, window_start_pct: float, window_end_pct: float,
                           rng: random.Random | None = None) -> None:
        """Ставит видео-наложение (и связанный звук «перед наложением») в случайную
        позицию так, чтобы клип целиком оставался в окне [start%..end%] длины ролika.
        Клип не обрезается."""
        rng = rng or random
        V = self.doc.total_duration
        overlay = self.layout.overlay_video_segment
        pre = self.layout.pre_overlay_sfx_segment
        o_start_old, o_dur = _target(overlay)
        pre_start_old, pre_dur = _target(pre)
        delta = pre_start_old - o_start_old

        lo = int(V * window_start_pct / 100.0)
        hi = int(V * window_end_pct / 100.0) - o_dur
        if hi < lo:
            # Окно уже клипа — центрируем по середине окна.
            center = int(V * (window_start_pct + window_end_pct) / 200.0)
            new_start = max(0, center - o_dur // 2)
            logger.warning("Окно наложения уже клипа — ставлю по центру окна.")
        else:
            new_start = rng.randint(lo, hi)

        _set_target(overlay, new_start, o_dur)
        _set_target(pre, new_start + delta, pre_dur)
        logger.info("Наложение поставлено на %.2fs (окно %.0f–%.0f%%).",
                    new_start / 1e6, window_start_pct, window_end_pct)

    # ---------------- субтитры ----------------

    def capture_subtitle_baseline(self) -> SubtitleBaseline:
        """Снимает оформление субтитров из исходного проекта (до удаления)."""
        base = SubtitleBaseline()
        segs = self.layout.text_segments
        if not segs:
            return base
        seg = segs[0]
        clip = seg.get("clip", {}) or {}
        scale = clip.get("scale", {}) or {}
        transform = clip.get("transform", {}) or {}
        base.scale_x = float(scale.get("x", 1.0))
        base.scale_y = float(scale.get("y", 1.0))
        base.transform_x = float(transform.get("x", 0.0))
        base.transform_y = float(transform.get("y", 0.0))

        # Шаблон субтитров.
        for mid in seg.get("extra_material_refs", []) + [seg.get("material_id", "")]:
            found = self.doc.material(mid)
            if found and found[0] == "text_templates":
                base.template_id = found[1].get("id", "")
                base.template_resource_id = found[1].get("resource_id", "")
        # Шрифт/стиль из текстового материала.
        for cat in ("texts",):
            for o in self.doc.materials.get(cat, []):
                if o.get("font_name"):
                    base.font_name = o.get("font_name", "")
                    base.font_id = o.get("font_id", "")
                    base.style_name = o.get("style_name", "")
                    break
        logger.info("Снят шаблон субтитров: template=%s font=%r scale=%.2f y=%.3f",
                    base.template_id[:8], base.font_name, base.scale_x, base.transform_y)
        return base

    def delete_subtitles(self) -> int:
        """Удаляет все субтитры (сегменты текст-дорожки и связанные материалы).
        Возвращает число удалённых сегментов."""
        track = self.layout.text_track
        if not track:
            return 0
        segs = list(track.get("segments", []))
        for seg in segs:
            for mid in [seg.get("material_id", "")] + seg.get("extra_material_refs", []):
                self.doc.remove_material(mid)
        track["segments"] = []
        logger.info("Удалено субтитров: %d", len(segs))
        return len(segs)

    def _seg_end(self, seg: dict) -> int:
        s, d = _target(seg)
        return s + d
