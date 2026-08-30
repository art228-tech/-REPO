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
    asr, assets, builder, diagnose, ffmpeg, naming, plan as plan_module,
    profile as profile_module, subtitles, textalign, validate,
)
from .config import Config
from .errors import PipelineError
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
    cues: list = field(default_factory=list)
    font_name: str = ""
    font_own: bool = True


# Сколько неудач подряд стерпеть, прежде чем признать, что материалы не подходят.
GIVE_UP_AFTER = 5

# Насколько сдвигается кадр в дополнительных роликах: на треть ширины в каждую
# сторону. Треть исходного кадра уходит, треть приходит с той стороны, которая
# в обычном ролике обрезана.
FRAME_SHIFT = 1 / 3


def frame_shifts(config: Config) -> list[float]:
    """Какие рамки собирать из одного набора материалов."""
    if not config.three_frames:
        return [0.0]
    return [0.0, -FRAME_SHIFT, FRAME_SHIFT]


@dataclass
class BatchReport:
    outcomes: list[VideoOutcome] = field(default_factory=list)
    stopped_reason: str = ""
    skipped: list[str] = field(default_factory=list)

    @property
    def made(self) -> int:
        return sum(1 for item in self.outcomes if item.ok)

    @property
    def failed(self) -> int:
        return sum(1 for item in self.outcomes if not item.ok)

    def summary(self) -> str:
        lines = [f"Готово роликов: {self.made}, пропущено: {self.failed}"]
        if self.stopped_reason:
            lines.append(f"Партия окончена раньше: {self.stopped_reason}")
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

        lines.extend(self._fonts())
        return "\n".join(lines)

    def _fonts(self) -> list[str]:
        """Сводка по шрифтам: одинаковые они в партии или нет."""
        made = [item for item in self.outcomes if item.ok and item.font_name]
        if not made:
            return []

        kinds = sorted({item.font_name for item in made})
        lines = [f"Шрифтов в партии: {len(kinds)} — {', '.join(kinds)}"]

        borrowed = sorted({item.template for item in made if not item.font_own})
        if borrowed:
            lines.append(
                f"  своего шрифта не нашлось у шаблонов: {', '.join(borrowed)} — "
                f"им подставлен общий запасной, поэтому шрифт у них одинаковый"
            )
        return lines


def discover_templates(config: Config) -> list[profile_module.TemplateProfile]:
    """Разбирает шаблоны и проверяет их пригодность до начала работы."""
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

    _check_subtitles(profiles, config)
    return profiles


def _check_subtitles(profiles: list[profile_module.TemplateProfile], config: Config) -> None:
    """Ловит шаблоны, в которых субтитры есть, но опознать их не удалось.

    Разница принципиальная. Если субтитров в шаблоне нет вовсе — это нормально,
    ролики просто соберутся без подписей. А если текстовые объекты есть, а
    дорожку найти не получилось, то оформление наследовать не от чего: ролик
    уйдёт с текстом из шаблона, то есть с чужими словами. Такое надо ловить
    заранее, а не после сотни собранных проектов.
    """
    broken = [p for p in profiles if p.subtitle_diagnosis.missing_but_present]
    if broken:
        names = ", ".join(p.name for p in broken)
        raise PipelineError(
            f"В шаблонах {names} не удалось опознать дорожку субтитров, хотя текст в них есть. "
            "Собранные ролики получили бы текст из шаблона вместо твоего. "
            "Скорее всего шаблон пересохранён CapCut в непривычном виде — "
            "пришли его мне, и я подстрою определитель."
        )

    for item in profiles:
        if item.subtitle_diagnosis.absent:
            if config.make_subtitles:
                log.warning(
                    "В шаблоне %s нет субтитров — ролики по нему будут без подписей",
                    item.name,
                )
            else:
                log.info("В шаблоне %s субтитров нет", item.name)


def run(config: Config, progress: Progress | None = None) -> BatchReport:
    ffmpeg.require_tools()
    report = BatchReport()

    seed = config.seed if config.seed is not None else int(time.time())
    rng = random.Random(seed)
    log.info("Зерно случайности: %s (с ним партия повторяется точь-в-точь)", seed)

    profiles = discover_templates(config)
    log.info("Шаблонов в ротации: %d — %s", len(profiles), ", ".join(p.name for p in profiles))

    clips = assets.Pool(config.clip_folders, assets.VIDEO_SUFFIXES, "клипы")
    voices = assets.Pool(config.voice_dir, assets.AUDIO_SUFFIXES, "озвучки")
    clips.shuffle(rng)
    voices.shuffle(rng)

    if len(voices) < config.count:
        log.warning("Озвучек %d, а заказано роликов %d — партия остановится раньше", len(voices), config.count)

    stamp = datetime.now().strftime("%m%d_%H%M")
    shifts = frame_shifts(config)
    if len(shifts) > 1:
        log.info("Из каждого набора материалов выйдет роликов: %d (сдвиги кадра %s)",
                 len(shifts), ", ".join(f"{s:+.0%}" if s else "обычный" for s in shifts))
    black = naming.black_background_numbers(config.count, config.black_bg_of_six, rng)
    if black:
        log.info("Без размытого фона: %d из %d (%d из каждых шести)",
                 len(black), config.count, config.black_bg_of_six)
    taken = naming.occupied(config.drafts_dir)

    # Одна неудачная озвучка не должна хоронить всю партию: такая озвучка
    # откладывается, и работа идёт дальше. Останавливаемся, только когда подряд
    # не выходит ничего — значит материалы и правда кончились.
    in_a_row = 0
    skipped: list[str] = []

    done = 0
    sets = 0
    while done < config.count:
        profile = profiles[sets % len(profiles)]
        portion = min(len(shifts), config.count - done)
        numbers = list(range(done + 1, done + 1 + portion))
        started = time.monotonic()

        if progress:
            progress(done + 1, config.count,
                     f"ролик {numbers[0]} из {config.count}, шаблон {profile.name}")

        made: list[VideoOutcome] = []
        try:
            made = _one(config, profile, clips, voices, rng, numbers, stamp,
                        shifts[:portion], black, taken)
        except PipelineError as exc:
            log.error("Ролики %s: %s", ", ".join(str(n) for n in numbers), exc)
            made = [VideoOutcome(number=n, template=profile.name, ok=False,
                                 error=str(exc)) for n in numbers]
        except Exception as exc:  # noqa: BLE001 - в журнал попадает всё
            log.error("Ролики %s упали: %s", ", ".join(str(n) for n in numbers), exc)
            log.debug("%s", traceback.format_exc())
            made = [VideoOutcome(number=n, template=profile.name, ok=False,
                                 error=f"неожиданная ошибка: {exc}") for n in numbers]

        spent = time.monotonic() - started
        for item in made:
            if not item.seconds:
                item.seconds = spent / max(1, len(made))
        report.outcomes.extend(made)

        done += portion
        sets += 1

        if all(item.ok for item in made):
            in_a_row = 0
            continue

        in_a_row += 1
        skipped.extend(item.error for item in made if not item.ok)
        outcome = next(item for item in made if not item.ok)

        if not len(voices):
            report.stopped_reason = "закончились озвучки"
            log.error("Озвучки закончились, партия окончена")
            break
        if in_a_row >= GIVE_UP_AFTER:
            report.stopped_reason = (
                f"{in_a_row} неудач подряд, последняя: {outcome.error}"
            )
            log.error("Подряд не вышло %d роликов — останавливаюсь, материалы не подходят",
                      in_a_row)
            break

        log.warning("Ролик %d пропущен, беру следующую озвучку", number)

    report.skipped = skipped

    log.info("%s", report.summary())
    return report


def _one(config: Config, profile, clips: assets.Pool, voices: assets.Pool,
         rng: random.Random, numbers: list[int], stamp: str, shifts: list[float],
         black: set[int], taken: set[str] | None = None) -> list[VideoOutcome]:
    """Собирает по одному набору материалов столько роликов, сколько задано кадров.

    Озвучка и клипы берутся один раз, а ролики из них выходят с разной рамкой:
    обычной и сдвинутой в стороны. Материалы расходуются тоже один раз, в конце.
    """
    voice = voices.take_next()
    log.info("Ролики %s: шаблон %s, озвучка %s (%.2fс)",
             ", ".join(str(n) for n in numbers), profile.name,
             voice.path.name, voice.duration_s)

    transcript = asr.transcribe(voice.path, config.asr_model, config.asr_language)

    script_path = textalign.find_script(voice.path)
    if script_path and transcript.has_words:
        script = script_path.read_text(encoding="utf-8", errors="replace")
        transcript.words = textalign.realign(transcript.words, script, transcript.duration)
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

    stretch = config.timing.max_clip_stretch
    chosen = [
        clips.take_longest_enough(us2s(line.slot_durations[0]), stretch),
        clips.take_longest_enough(us2s(line.slot_durations[1]), stretch),
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

    outcomes: list[VideoOutcome] = []
    for number, shift in zip(numbers, shifts):
        outcome = VideoOutcome(number=number, template=profile.name, ok=False)
        started = time.monotonic()
        try:
            outcome = _render(config, profile, render_plan, number, stamp, shift,
                              rng, black_background=number in black, taken=taken)
        except PipelineError as exc:
            outcome.error = str(exc)
            log.error("Ролик %d: %s", number, exc)
        finally:
            outcome.seconds = time.monotonic() - started
        outcomes.append(outcome)

    if config.consume_inputs:
        # Сценарий уносим вместе с озвучкой: они одно целое, и без этого в папке
        # копятся текстовики без своих звуковых файлов.
        used = [voice.path, chosen[0].path, chosen[1].path]
        if script_path:
            used.append(script_path)
        assets.consume(used, config.used_dir)

    return outcomes


def _render(config: Config, profile, render_plan, number: int, stamp: str,
            shift: float, rng: random.Random, black_background: bool,
            taken: set[str] | None) -> VideoOutcome:
    """Собирает один ролик из готового плана с заданной рамкой."""
    outcome = VideoOutcome(number=number, template=profile.name, ok=False)

    render_plan.black_background = black_background
    render_plan.frame_shift = shift
    if black_background:
        log.info("   ролик %d: фон погашен, под наложением чёрное поле", number)
    if shift:
        log.info("   ролик %d: кадр сдвинут %s на %.0f%% ширины",
                 number, "влево" if shift < 0 else "вправо", abs(shift) * 100)

    if config.random_names:
        name = naming.random_name(rng, config.name_length, taken)
        if taken is not None:
            taken.add(name)
    else:
        name = f"{config.name_prefix}_{stamp}_{number:03d}"
    result = builder.build(profile, render_plan, config, name)

    if config.make_subtitles and render_plan.cues and result.subtitle_count == 0:
        raise PipelineError(
            f"Реплик собрано {len(render_plan.cues)}, а в черновик не встала ни одна — "
            f"дорожку субтитров шаблона {profile.name} не удалось пересобрать. "
            "Ролик получился бы с текстом из шаблона, поэтому останавливаюсь."
        )

    checked = validate.check(result.folder)
    for warning in checked.warnings:
        log.warning("   проверка: %s", warning)
    if not checked.ok:
        for error in checked.errors:
            log.error("   проверка: %s", error)
        raise PipelineError(f"Черновик {name} не прошёл самопроверку, подробности в журнале")

    # Слепок субтитров снимаем с первого ролика партии: он маленький, а по нему
    # видно, чем собранный субтитр отличается от эталонного в шаблоне.
    if number == 1:
        try:
            report = diagnose.compare(profile.folder, result.folder)
            log.info("%s", report.describe())
            path = diagnose.write_bundle(report, config.log_dir)
            if report.problems:
                log.warning(
                    "Диагностика нашла %d расхождений. Если субтитров не видно, "
                    "пришли этот файл: %s", len(report.problems), path,
                )
        except Exception as exc:  # noqa: BLE001 - диагностика не должна валить сборку
            log.warning("Снять слепок субтитров не удалось: %s", exc)

    log.info("   готово: %s, %s, субтитров %d", name, fmt(result.duration_us), result.subtitle_count)

    outcome.ok = True
    outcome.name = name
    outcome.folder = result.folder
    outcome.duration_us = result.duration_us
    outcome.subtitle_count = result.subtitle_count
    outcome.notes = result.notes
    outcome.cues = render_plan.cues
    outcome.font_name = result.font_name
    outcome.font_own = result.font_own
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
