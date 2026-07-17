"""Headless-сборка видео по шаблону через FFmpeg.

Это кроссплатформенный рендер (работает и на сервере, и на ноуте) — им же
тестируется логика монтажа. На Windows основным считается CapCut-путь, а этот
служит эталоном/запаской.

Слои (снизу вверх):
  1. Размытая копия фона на весь экран (доп-фон).
  2. Основной фон — блок ~5:6 по центру.
  3. Субтитры (.ass, стиль «Сияние»).
  4. Эмодзи (появление «поп»).
  5. QR в конце: зум-вход 0.2с + лёгкое увеличение + осветление на выходе 0.2с.
Аудио: озвучка + (опц.) музыка тише + swoosh в начале.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..logging_setup import get_logger
from .media import probe_duration, run_ffmpeg

log = get_logger("montage.ffmpeg")


@dataclass
class EmojiHit:
    path: str
    start: float
    duration: float = 1.2
    size: int = 380          # сторона в пикселях
    anim: str = "zoom1"      # zoom1|zoom2|bounce1|bounce2 (в CapCut — точные пресеты)


@dataclass
class SoundHit:
    """Разовый звук (swoosh на переходе, акцент перед эмодзи/QR)."""
    path: str
    start: float = 0.0


@dataclass
class QrOverlay:
    path: str
    start: float             # когда появляется (обычно в конце)
    total: float = 1.2
    in_sec: float = 0.2
    out_sec: float = 0.2
    size: int = 520
    scale_grow: float = 1.08


@dataclass
class VideoSpec:
    out_path: str
    background: str                       # путь к фону
    bg_start: float = 0.0
    bg_length: float = 0.0                # 0 => вся длина от bg_start
    voiceover: str | None = None
    subtitles_ass: str | None = None
    music: str | None = None
    music_volume: float = 0.12
    swoosh: str | None = None
    sound_hits: list[SoundHit] = field(default_factory=list)   # акценты (эмодзи/QR)
    emojis: list[EmojiHit] = field(default_factory=list)
    qr: QrOverlay | None = None
    width: int = 1080
    height: int = 1920
    fps: int = 60
    blur: int = 40
    content_aspect: tuple[int, int] = (5, 6)
    duration: float = 0.0                 # 0 => по озвучке/фону
    duck_music: bool = True               # музыка приглушается под голос
    music_target_lufs: float = -26.0
    voice_target_lufs: float = -16.0


def _content_size(width: int, aspect: tuple[int, int]) -> tuple[int, int]:
    """Размер основного блока: ширина = экрану, высота по соотношению aspect."""
    aw, ah = aspect
    h = int(round(width * ah / aw))
    if h % 2:
        h += 1
    return width, h


def render_video(spec: VideoSpec) -> Path:
    out = Path(spec.out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # --- длительность ---
    duration = spec.duration
    if duration <= 0 and spec.voiceover:
        duration = probe_duration(spec.voiceover)
    if duration <= 0:
        bg_dur = probe_duration(spec.background)
        duration = spec.bg_length or bg_dur or 10.0
    duration = max(duration, 0.5)

    inputs: list[str] = []
    filt: list[str] = []

    # --- вход 0: основной фон (с обрезкой отрезка) ---
    bg_args = []
    if spec.bg_start > 0:
        bg_args += ["-ss", str(spec.bg_start)]
    seg_len = spec.bg_length if spec.bg_length > 0 else duration
    bg_args += ["-t", str(max(seg_len, duration)), "-i", spec.background]
    inputs += bg_args

    W, H, FPS = spec.width, spec.height, spec.fps
    cw, ch = _content_size(W, spec.content_aspect)

    # блюр-фон + основной блок
    filt.append(
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},gblur=sigma={spec.blur},setsar=1,fps={FPS}[bgblur]"
    )
    filt.append(
        f"[0:v]scale={cw}:-2:force_original_aspect_ratio=increase,"
        f"crop={cw}:{ch},setsar=1,fps={FPS}[main]"
    )
    filt.append(f"[bgblur][main]overlay=(W-w)/2:(H-h)/2:shortest=1[base0]")

    last_v = "base0"

    # субтитры
    if spec.subtitles_ass and Path(spec.subtitles_ass).exists():
        ass = str(spec.subtitles_ass).replace("\\", "/").replace(":", "\\:")
        filt.append(f"[{last_v}]ass='{ass}'[vsub]")
        last_v = "vsub"

    # --- аудио входы ---
    audio_labels: list[str] = []
    idx = 1
    voice_present = bool(spec.voiceover)
    music_present = bool(spec.music and Path(spec.music).exists())
    duck = spec.duck_music and voice_present and music_present

    if voice_present:
        inputs += ["-i", spec.voiceover]
        # нормализуем голос к целевой громкости
        filt.append(
            f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
            f"loudnorm=I={spec.voice_target_lufs}:TP=-1.5:LRA=11[voa0]"
        )
        if duck:
            # копия голоса как сайд-чейн для приглушения музыки
            filt.append("[voa0]asplit=2[voa][vosc]")
        else:
            filt.append("[voa0]anull[voa]")
        audio_labels.append("voa")
        idx += 1
    if music_present:
        inputs += ["-stream_loop", "-1", "-i", spec.music]
        # музыку нормализуем к более тихой цели (не громко, но и не тихо)
        filt.append(
            f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
            f"loudnorm=I={spec.music_target_lufs}:TP=-2:LRA=11,"
            f"atrim=0:{duration}[mua0]"
        )
        if duck:
            # музыка приглушается, когда идёт голос (sidechain compressor)
            filt.append(
                "[mua0][vosc]sidechaincompress=threshold=0.03:ratio=8:"
                "attack=5:release=250[mua]"
            )
        else:
            filt.append("[mua0]anull[mua]")
        audio_labels.append("mua")
        idx += 1
    if spec.swoosh and Path(spec.swoosh).exists():
        inputs += ["-i", spec.swoosh]
        filt.append(
            f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
            f"adelay=0|0[swa]"
        )
        audio_labels.append("swa")
        idx += 1

    # акцент-звуки (перед эмодзи и перед QR), каждый со своим сдвигом
    for hit_i, hit in enumerate(spec.sound_hits):
        if not Path(hit.path).exists():
            continue
        delay_ms = int(max(hit.start, 0.0) * 1000)
        inputs += ["-i", hit.path]
        filt.append(
            f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
            f"adelay={delay_ms}|{delay_ms}[hit{hit_i}]"
        )
        audio_labels.append(f"hit{hit_i}")
        idx += 1

    # --- эмодзи (появление «поп» через fade по альфе) ---
    for emo in spec.emojis:
        if not Path(emo.path).exists():
            log.warning("Эмодзи не найден: %s", emo.path)
            continue
        inputs += ["-loop", "1", "-t", str(emo.duration), "-itsoffset",
                   str(emo.start), "-i", emo.path]
        pop = min(0.18, emo.duration / 3)
        filt.append(
            f"[{idx}:v]scale={emo.size}:-1,format=rgba,"
            f"fade=t=in:st={emo.start}:d={pop}:alpha=1,"
            f"fade=t=out:st={emo.start + emo.duration - pop}:d={pop}:alpha=1[emo{idx}]"
        )
        filt.append(
            f"[{last_v}][emo{idx}]overlay=(W-w)/2:(H-h)/2:"
            f"enable='between(t,{emo.start},{emo.start + emo.duration})'[vemo{idx}]"
        )
        last_v = f"vemo{idx}"
        idx += 1

    # --- QR в конце: рост от центра + осветление на выходе ---
    # Примечание: zoompan не сохраняет альфу, поэтому центрируем зум по iw/ih.
    # Точные пресеты «zoom1 вход / осветление» делаются нативно в CapCut;
    # тут — функциональный эталон: центрированный рост + вход/выход.
    if spec.qr and Path(spec.qr.path).exists():
        q = spec.qr
        inputs += ["-loop", "1", "-t", str(q.total), "-itsoffset",
                   str(q.start), "-i", q.path]
        frames = max(int(q.total * FPS), 1)
        grow_per_frame = (q.scale_grow - 1.0) / frames
        filt.append(
            f"[{idx}:v]scale={q.size}:{q.size},setsar=1,"
            f"zoompan=z='min(1+{grow_per_frame:.6f}*on,{q.scale_grow:.4f})':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={q.size}x{q.size}:fps={FPS},"
            f"fade=t=in:st=0:d={q.in_sec},"
            f"fade=t=out:st={q.total - q.out_sec}:d={q.out_sec}:color=white[qr]"
        )
        filt.append(
            f"[{last_v}][qr]overlay=(W-w)/2:(H-h)/2:"
            f"enable='between(t,{q.start},{q.start + q.total})'[vqr]"
        )
        last_v = "vqr"
        idx += 1

    # финальный видеопоток по длительности
    filt.append(f"[{last_v}]trim=0:{duration},setpts=PTS-STARTPTS[vout]")

    # --- сведение аудио ---
    a_out = None
    if audio_labels:
        if len(audio_labels) == 1:
            filt.append(f"[{audio_labels[0]}]atrim=0:{duration}[aout]")
        else:
            joined = "".join(f"[{lbl}]" for lbl in audio_labels)
            filt.append(
                f"{joined}amix=inputs={len(audio_labels)}:duration=longest:"
                f"dropout_transition=0,atrim=0:{duration}[aout]"
            )
        a_out = "aout"

    args = [*inputs, "-filter_complex", ";".join(filt), "-map", "[vout]"]
    if a_out:
        args += ["-map", f"[{a_out}]"]
    args += [
        "-r", str(FPS), "-c:v", "libx264", "-preset", "medium",
        "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-t", str(duration),
        str(out),
    ]
    log.info("Рендер %s (%.2fс, %dx%d@%d)", out.name, duration, W, H, FPS)
    run_ffmpeg(args)
    return out
