"""Партия роликов: от папок с материалами до готовых черновиков в CapCut."""
from __future__ import annotations

import random
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import (
    asr, assets, builder, ffmpeg, plan as plan_module, profile as profile_module,
    subtitles, textalign, validate,
)
from .config import Config
from .errors import AssetShortage, PipelineError
from .logging_setup import get_logger
from .plan import Cue
from .units import fmt, us2s

log = get_logger("batch")

Progress = Callable[[int, int, str], None]


@dataclass
class VideoOutcome:
    number: int
    template: str
    ok: bool
    name: str = ""
    folder: Path | None = None
    duration_us: int = 0
    subtitle_count: int = 0
    error: str = ""
    notes: list[str] = field(default_factory=list)
    seconds: float = 0.0


@dataclass
class BatchReport:
    outcomes: list[VideoOutcome] = field(default_factory=list)
    stopped_reason: str = ""

    @property
    def made(self) -> int:
        return sum(1 for item in self.outcomes if item.ok)

    @property
    def failed(self) -> int:
        return sum(1 for item in self.outcomes if not item.ok)

    def summary(self) -> str:
        lines = [f"Готово роликов: {self.made}, с ошибкой: {self.failed}"]
        if self.stopped_reason:
            lines.append(f"Партия остановлена: {self.stopped_reason}")
        for item in self.outcomes:
            mark = "+" if item.ok else "x"
            head = f"  {mark} #{item.number} {item.template}"
            if item.ok:
                head += f" → {item.name}, {fmt(item.duration_us)}, субтитров {item.subtitle_count}, {item.seconds:.1f}с"
            else:
                head += f" — {item.error}"
            lines.append(head)
            for note in item.notes:
                lines.append(f"      ! {note}")
        return "\n".join(lines)


def discover_templates(config: Config) -> list[profile_module.TemplateProfile]:
    """Разбирает шаблоны, перечисленные в настройках."""
    names = config.templates or []
    if not names:
        raise PipelineError("Не выбран ни один шаблон")

    profiles = []
    for name in names:
        folder = Path(name)
        if not folder.is_absolute():
            folder = config.drafts_dir / name
        if not folder.is_dir():
            raise PipelineError(f"Шаблон не найден: {folder}")
        profiles.append(profile_module.analyse(folder))
    return profiles


def run(config: Config, progress: Progress | None = None) -> BatchReport:
    ffmpeg.require_tools()
    report = BatchReport()

    seed = config.seed if config.seed is not None else int(time.time())
    rng = random.Random(seed)
    log.info("Зерно случайности: %s (с ним партия повторяется точь-в-точь)", seed)

    profiles = discover_templates(config)
    log.info("Шаблонов в ротации: %d — %s", len(profiles), ", ".join(p.name for p in profiles))
    for item in profiles:
        log.debug("%s", item.describe())

    clips = assets.Pool(config.clips_dir, assets.VIDEO_SUFFIXES, "клипы")
    voices = assets.Pool(config.voice_dir, assets.AUDIO_SUFFIXES, "озвучки")
    clips.shuffle(rng)
    voices.shuffle(rng)

    if len(voices) < config.count:
        log.warning("Озвучек %d, а заказано роликов %d — партия остановится раньше", len(voices), config.count)

    stamp = datetime.now().strftime("%m%d_%H%M")

    for number in range(1, config.count + 1):
        profile = profiles[(number - 1) % len(profiles)]
        started = time.monotonic()
        outcome = VideoOutcome(number=number, template=profile.name, ok=False)
        if progress:
            progress(number, config.count, f"ролик {number} из {config.count}, шаблон {profile.name}")

        try:
            outcome = _one(config, profile, clips, voices, rng, number, stamp)
        except AssetShortage as exc:
            outcome.error = str(exc)
            report.outcomes.append(outcome)
            report.stopped_reason = str(exc)
            log.error("Ролик %d: %s", number, exc)
            log.error("Партия остановлена — материалы закончились")
            break
        except PipelineError as exc:
            outcome.error = str(exc)
            log.error("Ролик %d: %s", number, exc)
        except Exception as exc:  # noqa: BLE001 - в журнал попадает всё
            outcome.error = f"неожиданная ошибка: {exc}"
            log.error("Ролик %d упал: %s", number, exc)
            log.debug("%s", traceback.format_exc())
        finally:
            outcome.seconds = time.monotonic() - started

        report.outcomes.append(outcome)
        if not outcome.ok:
            report.stopped_reason = outcome.error
            log.error("Партия остановлена на ролике %d", number)
            break

    log.info("%s", report.summary())
    return report


def _one(config: Config, profile, clips: assets.Pool, voices: assets.Pool,
         rng: random.Random, number: int, stamp: str) -> VideoOutcome:
    outcome = VideoOutcome(number=number, template=profile.name, ok=False)

    voice = voices.take_next()
    log.info("Ролик %d: шаблон %s, озвучка %s (%.2fс)", number, profile.name, voice.path.name, voice.duration_s)

    transcript = asr.transcribe(voice.path, config.asr_model, config.asr_language)

    script_path = textalign.find_script(voice.path)
    if script_path and transcript.has_words:
        script = script_path.read_text(encoding="utf-8", errors="replace")
        transcript.words = textalign.realign(transcript.words, script)
        log.info("   текст субтитров взят из сценария %s", script_path.name)
    elif script_path:
        log.warning("   сценарий %s найден, но речь не распознана — выравнивать не по чему", script_path.name)

    trailing = ffmpeg.trailing_silence(voice.path, config.timing.silence_db)
    log.debug("тишина в конце озвучки: %.3fс, источник разбора: %s", trailing, transcript.source)

    line = plan_module.timeline(profile, config, transcript, trailing)
    log.info(
        "   длина ролика %s, стык %s (%s), слоты %s и %s",
        fmt(line.total_us), fmt(line.cut_us), line.cut_reason,
        fmt(line.slot_durations[0]), fmt(line.slot_durations[1]),
    )

    chosen = [
        clips.take_longest_enough(us2s(line.slot_durations[0])),
        clips.take_longest_enough(us2s(line.slot_durations[1])),
    ]
    log.info("   клипы: %s (%.2fс) и %s (%.2fс)",
             chosen[0].path.name, chosen[0].duration_s, chosen[1].path.name, chosen[1].duration_s)

    render_plan = plan_module.build(
        profile, config, line, voice.path,
        [c.path for c in chosen], [c.duration_s for c in chosen], rng,
    )

    if config.make_subtitles:
        render_plan.cues = _cues_for(transcript, config, line)
        if not render_plan.cues:
            render_plan.notes.append("субтитры не собраны: речь не распознана")

    log.debug("план:\n%s", render_plan.describe())

    name = f"{config.name_prefix}_{stamp}_{number:03d}"
    result = builder.build(profile, render_plan, config, name)

    report = validate.check(result.folder)
    for warning in report.warnings:
        log.warning("   проверка: %s", warning)
    if not report.ok:
        for error in report.errors:
            log.error("   проверка: %s", error)
        raise PipelineError(f"Черновик {name} не прошёл самопроверку, подробности в журнале")

    if config.consume_inputs:
        assets.consume([voice.path, chosen[0].path, chosen[1].path], config.used_dir)

    log.info("   готово: %s, %s, субтитров %d", name, fmt(result.duration_us), result.subtitle_count)

    outcome.ok = True
    outcome.name = name
    outcome.folder = result.folder
    outcome.duration_us = result.duration_us
    outcome.subtitle_count = result.subtitle_count
    outcome.notes = result.notes
    return outcome


def _cues_for(transcript, config: Config, line) -> list[Cue]:
    """Реплики субтитров, сдвинутые на положение озвучки и обрезанные по концу ролика."""
    cues = subtitles.build_cues(transcript, config.timing)
    shifted: list[Cue] = []
    for cue in cues:
        start = cue.start_us + line.voice_start_us
        end = min(start + cue.duration_us, line.total_us)
        if end <= start:
            continue
        shifted.append(Cue(text=cue.text, start_us=start, duration_us=end - start, words=cue.words))
    return shifted
