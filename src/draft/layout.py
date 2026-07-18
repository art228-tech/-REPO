"""Распознавание ролей сегментов на таймлайне проекта.

Проект-шаблон пользователя всегда одинаковой структуры (CapCut 9.0.0, 9:16):

  видео-дорожки:
    * размытый фон       — видео с эффектом «Размытие» (2 сегмента: вступление + основной)
    * передний фон       — тот же ролик без блюра (2 сегмента: вступление + основной)
    * наложение + фото   — сегмент-наложение (хромакей) + фото в конце
  текст-дорожка          — субтитры
  аудио-дорожки:
    * озвучка            — один сегмент на весь ролик, громкая (задаёт длину)
    * фоновая музыка     — один сегмент на весь ролик, тихая
    * звуки              — 3 коротких: свуш-переход, перед наложением, перед фото

Идентификация — семантическая (по типам/эффектам/громкости/позиции), чтобы не
зависеть жёстко от порядка дорожек.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .document import DraftDocument


def _seg_start(seg: dict) -> int:
    return int(seg.get("target_timerange", {}).get("start", 0))


def _seg_dur(seg: dict) -> int:
    return int(seg.get("target_timerange", {}).get("duration", 0))


def _seg_end(seg: dict) -> int:
    return _seg_start(seg) + _seg_dur(seg)


class LayoutError(Exception):
    pass


@dataclass
class TimelineLayout:
    doc: DraftDocument

    blurred_track: dict = field(init=False)
    foreground_track: dict = field(init=False)
    overlay_track: dict = field(init=False)
    text_track: dict | None = field(init=False, default=None)
    voiceover_track: dict = field(init=False)
    bgmusic_track: dict = field(init=False)
    sfx_track: dict = field(init=False)

    def __post_init__(self) -> None:
        self._detect()

    # ---- детекторы ----

    def _seg_material_type(self, seg: dict) -> str:
        obj = self.doc.material_obj(seg.get("material_id", ""))
        return obj.get("type", "") if obj else ""

    def _seg_has_video_effect(self, seg: dict) -> bool:
        for mid in seg.get("extra_material_refs", []):
            found = self.doc.material(mid)
            if found and found[0] == "video_effects":
                return True
        return False

    def _detect(self) -> None:
        video_tracks = [t for t in self.doc.tracks if t.get("type") == "video"]
        audio_tracks = [t for t in self.doc.tracks if t.get("type") == "audio"]
        text_tracks = [t for t in self.doc.tracks if t.get("type") == "text"]

        if len(video_tracks) < 3:
            raise LayoutError(f"Ожидалось 3 видео-дорожки, найдено {len(video_tracks)}")
        if len(audio_tracks) < 3:
            raise LayoutError(f"Ожидалось 3 аудио-дорожки, найдено {len(audio_tracks)}")

        # Наложение+фото: видео-дорожка, содержащая сегмент-фото.
        overlay = None
        for t in video_tracks:
            if any(self._seg_material_type(s) == "photo" for s in t.get("segments", [])):
                overlay = t
                break
        if overlay is None:
            raise LayoutError("Не найдена дорожка с фото (наложение+фото)")
        self.overlay_track = overlay

        rest = [t for t in video_tracks if t is not overlay]
        # Размытый фон: содержит видео-эффект (блюр) хотя бы в одном сегменте.
        blurred = next(
            (t for t in rest if any(self._seg_has_video_effect(s) for s in t.get("segments", []))),
            None,
        )
        if blurred is None:
            # запасной вариант — дорожка с наибольшим масштабом сегмента
            blurred = max(rest, key=lambda t: _max_scale(t))
        self.blurred_track = blurred
        self.foreground_track = next(t for t in rest if t is not blurred)

        self.text_track = text_tracks[0] if text_tracks else None

        # Аудио: sfx = дорожка с несколькими сегментами; остальные — полноразмерные.
        sfx = max(audio_tracks, key=lambda t: len(t.get("segments", [])))
        self.sfx_track = sfx
        full = [t for t in audio_tracks if t is not sfx]
        # Озвучка — громче, фоновая музыка — тише.
        full.sort(key=lambda t: _first_seg_volume(t), reverse=True)
        self.voiceover_track = full[0]
        self.bgmusic_track = full[-1]

    # ---- удобные геттеры сегментов ----

    def _sorted_video_segs(self, track: dict) -> list[dict]:
        return sorted(track.get("segments", []), key=_seg_start)

    @property
    def bg_intro_segments(self) -> list[dict]:
        """Вступительный (короткий) фон: seg0 размытого и переднего фона."""
        return [self._sorted_video_segs(self.blurred_track)[0],
                self._sorted_video_segs(self.foreground_track)[0]]

    @property
    def bg_main_segments(self) -> list[dict]:
        """Основной фон: seg1 размытого и переднего фона."""
        return [self._sorted_video_segs(self.blurred_track)[1],
                self._sorted_video_segs(self.foreground_track)[1]]

    @property
    def overlay_video_segment(self) -> dict:
        segs = [s for s in self.overlay_track.get("segments", [])
                if self._seg_material_type(s) != "photo"]
        return sorted(segs, key=_seg_start)[0]

    @property
    def photo_segment(self) -> dict:
        segs = [s for s in self.overlay_track.get("segments", [])
                if self._seg_material_type(s) == "photo"]
        return sorted(segs, key=_seg_start)[0]

    @property
    def voiceover_segment(self) -> dict:
        return self._sorted_video_segs(self.voiceover_track)[0]

    @property
    def bgmusic_segment(self) -> dict:
        return self._sorted_video_segs(self.bgmusic_track)[0]

    @property
    def sfx_segments(self) -> list[dict]:
        """Отсортированы по времени: [свуш-переход, перед наложением, перед фото]."""
        return sorted(self.sfx_track.get("segments", []), key=_seg_start)

    @property
    def transition_sfx_segment(self) -> dict:
        return self.sfx_segments[0]

    @property
    def pre_overlay_sfx_segment(self) -> dict:
        segs = self.sfx_segments
        return segs[1] if len(segs) >= 3 else segs[-1]

    @property
    def pre_photo_sfx_segment(self) -> dict:
        return self.sfx_segments[-1]

    @property
    def text_segments(self) -> list[dict]:
        if not self.text_track:
            return []
        return list(self.text_track.get("segments", []))

    def describe(self) -> str:
        def d(seg):
            return f"[{_seg_start(seg)/1e6:.2f}+{_seg_dur(seg)/1e6:.2f}]"
        lines = [
            f"Размытый фон: intro {d(self.bg_intro_segments[0])} main {d(self.bg_main_segments[0])}",
            f"Передний фон: intro {d(self.bg_intro_segments[1])} main {d(self.bg_main_segments[1])}",
            f"Наложение: {d(self.overlay_video_segment)}  Фото: {d(self.photo_segment)}",
            f"Озвучка: {d(self.voiceover_segment)}  Фон.музыка: {d(self.bgmusic_segment)}",
            f"Звуки: переход {d(self.transition_sfx_segment)} "
            f"перед-налож {d(self.pre_overlay_sfx_segment)} перед-фото {d(self.pre_photo_sfx_segment)}",
            f"Субтитров: {len(self.text_segments)}",
        ]
        return "\n".join(lines)


def _max_scale(track: dict) -> float:
    best = 0.0
    for s in track.get("segments", []):
        sc = (s.get("clip", {}) or {}).get("scale", {}) or {}
        best = max(best, float(sc.get("x", 0)))
    return best


def _first_seg_volume(track: dict) -> float:
    segs = track.get("segments", [])
    return float(segs[0].get("volume", 1.0)) if segs else 0.0
