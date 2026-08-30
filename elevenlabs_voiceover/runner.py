"""Оркестратор: создание голосов и пакетная озвучка текстов."""

from __future__ import annotations

import csv
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import audio as audio_utils
from .api_client import ElevenLabsClient, ModelInfo, Subscription
from .chunker import Chunk, split_text
from .config import (
    DONE_DELETE,
    DONE_FOLDER_NAME,
    DONE_KEEP,
    MODE_ALL_VOICES,
    SOURCE_ACCOUNT,
    SOURCE_DESIGN,
    Settings,
)
from .errors import (
    Cancelled,
    ElevenLabsError,
    PlanLimitation,
    ProxyFailure,
    QuotaExceeded,
    ValidationFailed,
    VoiceLimitReached,
)
from .logging_setup import get_logger
from .state import StateStore, StoredVoice, digest

log = get_logger("runner")

#: Кодировки, в которых на Windows обычно оказываются txt-файлы.
_ENCODINGS = ("utf-8-sig", "utf-8", "cp1251", "cp1252", "koi8-r")

#: Как часто сверять локальный счётчик расхода с реальным остатком на сервере.
_QUOTA_RESYNC_EVERY = 15

#: Сколько символов соседнего куска передавать как контекст для ровных стыков.
_CONTEXT_CHARS = 600

ProgressCallback = Callable[[float, str], None]


# ----------------------------------------------------------------------
@dataclass
class PromptSpec:
    path: Path
    name: str
    description: str


@dataclass
class TextSpec:
    path: Path
    name: str
    text: str = ""
    chunks: List[Chunk] = field(default_factory=list)
    loaded: bool = False

    @property
    def characters(self) -> int:
        return sum(c.characters for c in self.chunks)


@dataclass
class VoiceRef:
    voice_id: str
    name: str
    prompt_file: str
    reused: bool


@dataclass
class Job:
    text: TextSpec
    voice: VoiceRef
    output_path: Path
    duration: Optional[float] = None


@dataclass
class RunStats:
    voices_created: int = 0
    voices_reused: int = 0
    texts_total: int = 0
    texts_done: int = 0
    texts_skipped: int = 0
    texts_failed: int = 0
    chunks_done: int = 0
    chunks_reused: int = 0
    characters_spent: int = 0
    credits_estimated: float = 0.0
    seconds_produced: float = 0.0
    stopped_reason: str = ""
    failures: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {
            "voices_created": self.voices_created,
            "voices_reused": self.voices_reused,
            "texts_total": self.texts_total,
            "texts_done": self.texts_done,
            "texts_skipped": self.texts_skipped,
            "texts_failed": self.texts_failed,
            "chunks_done": self.chunks_done,
            "chunks_reused": self.chunks_reused,
            "characters_spent": self.characters_spent,
            "credits_estimated": round(self.credits_estimated, 1),
            "audio_duration": audio_utils.format_duration(self.seconds_produced),
            "stopped_reason": self.stopped_reason,
            "failures": self.failures[:50],
        }


class PreflightError(Exception):
    """Проблема в настройках, из-за которой запускать работу бессмысленно."""


# ----------------------------------------------------------------------
def _pace(characters: int, seconds: Optional[float]) -> Optional[float]:
    """Темп речи в символах за секунду.

    Число, по которому голоса сравниваются между собой: длина текста сама по
    себе ничего не говорит о том, быстро ли его прочитали.
    """
    if not seconds or seconds <= 0 or characters <= 0:
        return None
    return characters / seconds


def read_text_file(path: Path) -> str:
    """Прочитать txt, самостоятельно определив кодировку.

    На Windows файлы часто лежат в cp1251, и молча получить кракозябры в
    озвучке (за деньги) — худший из возможных исходов.
    """
    data = path.read_bytes()
    if not data.strip():
        return ""

    for encoding in _ENCODINGS:
        try:
            decoded = data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        # Символ замены означает, что кодировка угадана неверно.
        if "\ufffd" in decoded:
            continue
        return decoded

    log.warning("Не удалось надёжно определить кодировку %s, читаю как utf-8 с заменой", path.name)
    return data.decode("utf-8", errors="replace")


def natural_key(name: str) -> Tuple:
    """Ключ сортировки, при котором text2 идёт раньше text10."""
    parts = re.split(r"(\d+)", name.lower())
    return tuple(int(p) if p.isdigit() else p for p in parts)


def list_txt_files(directory: Path) -> List[Path]:
    if not directory.is_dir():
        return []
    files = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".txt"]
    return sorted(files, key=lambda p: natural_key(p.name))


def count_txt_files(directory: Path) -> int:
    """Сколько .txt лежит прямо в папке — без открытия файлов."""
    try:
        with os.scandir(directory) as entries:
            return sum(
                1
                for entry in entries
                if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".txt")
            )
    except OSError:
        return 0


# ----------------------------------------------------------------------
class Runner:
    def __init__(
        self,
        settings: Settings,
        state: StateStore,
        *,
        cancel_event: Optional[threading.Event] = None,
        on_progress: Optional[ProgressCallback] = None,
    ) -> None:
        self.settings = settings
        self.state = state
        self.cancel = cancel_event or threading.Event()
        self._on_progress = on_progress

        self.stats = RunStats()
        self._client: Optional[ElevenLabsClient] = None
        self._model: Optional[ModelInfo] = None
        self._subscription: Optional[Subscription] = None
        self._credits_used_locally = 0.0
        self._credits_budget = 0.0
        self._requests_since_sync = 0
        self._voice_slots_baseline: Optional[int] = None
        self._total_units = 1
        self._done_units = 0

    # ------------------------------------------------------------------
    def _progress(self, message: str) -> None:
        if self._on_progress:
            fraction = min(1.0, self._done_units / self._total_units) if self._total_units else 0.0
            try:
                self._on_progress(fraction, message)
            except Exception:  # noqa: BLE001
                pass

    def _check_cancelled(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()

    # ------------------------------------------------------------------
    def run(self) -> RunStats:
        run_id = self.state.start_run()
        outcome = "error"
        try:
            self._run_inner()
            outcome = "cancelled" if self.cancel.is_set() else "ok"
        except Cancelled:
            outcome = "cancelled"
            self.stats.stopped_reason = self.stats.stopped_reason or "Остановлено пользователем"
            log.info("Работа остановлена пользователем")
        except QuotaExceeded as exc:
            outcome = "quota"
            self.stats.stopped_reason = "Кредиты на аккаунте закончились"
            log.warning("%s", exc)
        except PreflightError as exc:
            outcome = "preflight"
            self.stats.stopped_reason = str(exc)
            log.error("Проверка перед запуском не пройдена: %s", exc)
            raise
        except PlanLimitation as exc:
            outcome = "plan_limit"
            self.stats.stopped_reason = str(exc)
            log.error("%s", exc)
        except ProxyFailure as exc:
            outcome = "proxy_error"
            self.stats.stopped_reason = str(exc)
            log.error("%s", exc)
            log.error(
                "Нажмите «Проверить соединение» — программа переберёт схемы прокси "
                "и подскажет рабочую, либо очистите поле «Прокси» в настройках."
            )
        except ElevenLabsError as exc:
            outcome = "api_error"
            self.stats.stopped_reason = str(exc)
            log.error("Ошибка API, работа остановлена: %s", exc, exc_info=True)
        except Exception as exc:
            outcome = "error"
            self.stats.stopped_reason = f"Непредвиденная ошибка: {exc}"
            log.exception("Непредвиденная ошибка")
        finally:
            if self._client:
                self._client.close()
            self.state.finish_run(run_id, outcome, self.stats.as_dict())
            log.info("Итог прогона (%s): %s", outcome, self.stats.as_dict())

        return self.stats

    # ------------------------------------------------------------------
    def _run_inner(self) -> None:
        settings = self.settings

        prompts_dir = Path(settings.prompts_dir)
        texts_dir = Path(settings.texts_dir)
        output_dir = Path(settings.output_dir)

        if not settings.resolved_api_key():
            raise PreflightError("Не указан API-ключ")
        if settings.voice_source == SOURCE_DESIGN and not prompts_dir.is_dir():
            raise PreflightError(f"Папка с промптами голосов не найдена: {prompts_dir}")
        if not texts_dir.is_dir():
            raise PreflightError(f"Папка с текстами не найдена: {texts_dir}")
        # Служебные файлы — превью голосов, промежуточные куски, манифест —
        # кладём туда же, куда и результат, чтобы всё лежало рядом.
        if settings.save_next_to_texts:
            service_dir = texts_dir
        else:
            if not settings.output_dir:
                raise PreflightError("Не выбрана папка для результатов")
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise PreflightError(f"Не удалось создать папку результатов: {exc}") from exc
            service_dir = output_dir

        from_account = settings.voice_source == SOURCE_ACCOUNT
        prompts = [] if from_account else self._load_prompts(prompts_dir)
        texts = self._load_texts(texts_dir)

        self._client = ElevenLabsClient(
            settings.resolved_api_key(),
            timeout=settings.request_timeout,
            max_retries=settings.max_retries,
            cancel_event=self.cancel,
            proxy_url=settings.proxy_url,
            ignore_system_proxy=settings.ignore_system_proxy,
        )

        self._sync_subscription(initial=True)
        self._resolve_model()

        if from_account:
            voices = self._voices_from_account()
        else:
            voices = self._prepare_voices(prompts, service_dir)
        if not voices:
            raise PreflightError("Не удалось подготовить ни одного голоса")

        jobs = self._build_jobs(texts, voices, service_dir)
        self.stats.texts_total = len(jobs)

        self._total_units = max(1, len(jobs))
        self._done_units = 0

        log.info(
            "К озвучке %d заданий. Доступно %s кредитов. "
            "Тексты читаю по одному, когда до них дойдёт очередь",
            len(jobs),
            f"{self._credits_budget:,.0f}".replace(",", " "),
        )

        jobs_by_text: Dict[Path, List[Job]] = {}
        for job in jobs:
            jobs_by_text.setdefault(job.text.path, []).append(job)

        try:
            for job in jobs:
                self._check_cancelled()
                if not self._ensure_text_loaded(job.text):
                    self._done_units += 1
                    continue
                if not self._has_budget_for(job.text.chunks[0].characters if job.text.chunks else 0):
                    self.stats.stopped_reason = "Кредиты закончились"
                    log.warning("Кредиты закончились, останавливаюсь до следующего файла")
                    break
                self._process_job(job)
                self._retire_source(job.text, jobs_by_text[job.text.path])
        finally:
            # Манифест нужен и при остановке по кредитам или по кнопке: он
            # показывает, что успело озвучиться и каким голосом.
            self._write_manifest(jobs, service_dir)

    # ------------------------------------------------------------------
    def _load_prompts(self, directory: Path) -> List[PromptSpec]:
        files = list_txt_files(directory)
        if not files:
            raise PreflightError(f"В папке промптов нет ни одного .txt файла: {directory}")

        prompts: List[PromptSpec] = []
        for path in files:
            description = read_text_file(path).strip()
            if not description:
                log.warning("Промпт %s пустой, пропускаю", path.name)
                continue
            if len(description) > 2000:
                log.warning("Промпт %s очень длинный, обрезаю до 2000 символов", path.name)
                description = description[:2000]
            prompts.append(PromptSpec(path=path, name=path.stem, description=description))

        if not prompts:
            raise PreflightError("Все файлы промптов пустые")

        limit = self.settings.max_voices
        if len(prompts) > limit:
            log.info("Найдено %d промптов, беру первые %d по настройке", len(prompts), limit)
            prompts = prompts[:limit]
        return prompts

    def _load_texts(self, directory: Path) -> List[TextSpec]:
        """Только список файлов: содержимое читается в момент озвучки."""
        self._progress("Смотрю папку с текстами…")
        files = list_txt_files(directory)
        if not files:
            raise PreflightError(f"В папке текстов нет ни одного .txt файла: {directory}")
        log.info(
            "Найдено %d текстов, каждый открою только когда до него дойдёт очередь",
            len(files),
        )
        self._progress(f"Найдено текстов: {len(files)}")
        return [TextSpec(path=path, name=path.stem) for path in files]

    def _ensure_text_loaded(self, spec: TextSpec) -> bool:
        """Прочитать и нарезать один текст. False, если файл пустой или не читается."""
        if spec.loaded:
            return bool(spec.chunks)
        spec.loaded = True
        try:
            spec.text = read_text_file(spec.path)
        except OSError as exc:
            log.warning("Не удалось прочитать %s (%s), пропускаю", spec.path.name, exc)
            return False
        max_chars = self._model.max_chars_per_request if self._model else 0
        spec.chunks = split_text(
            spec.text,
            self.settings.chunk_target_chars,
            max_chars,
            line_breaks=self.settings.line_breaks,
        )
        if not spec.chunks:
            log.warning("Текст %s пустой, пропускаю", spec.path.name)
            return False
        return True

    # ------------------------------------------------------------------
    def _resolve_model(self) -> None:
        assert self._client is not None
        try:
            models = self._client.list_models()
        except ElevenLabsError as exc:
            log.warning("Не удалось получить список моделей (%s), беру настройки как есть", exc)
            return

        wanted = self.settings.model_id
        for model in models:
            if model.model_id == wanted:
                self._model = model
                log.info(
                    "Модель %s: %g кредита за символ, до %d символов за запрос",
                    model.model_id,
                    model.cost_multiplier,
                    model.max_chars_per_request,
                )
                return

        available = ", ".join(m.model_id for m in models if m.can_do_text_to_speech)
        raise PreflightError(f"Модель {wanted} недоступна на вашем аккаунте. Доступны: {available}")

    def _cost_multiplier(self) -> float:
        return self._model.cost_multiplier if self._model else 1.0

    # ------------------------------------------------------------------
    def _sync_subscription(self, initial: bool = False) -> None:
        assert self._client is not None
        subscription = self._client.get_subscription()
        self._subscription = subscription
        self._credits_used_locally = 0.0
        self._requests_since_sync = 0

        budget = subscription.credits_left - self.settings.reserve_credits
        self._credits_budget = max(0.0, float(budget))

        if initial:
            log.info("Аккаунт: %s", subscription.summary())
            if self.settings.reserve_credits:
                log.info("В запасе оставляю %d кредитов", self.settings.reserve_credits)
            if self._credits_budget <= 0:
                raise PreflightError(
                    f"Доступных кредитов нет: остаток {subscription.credits_left}, "
                    f"резерв {self.settings.reserve_credits}"
                )
        else:
            log.debug("Сверка остатка: %s", subscription.summary())

    def _credits_left(self) -> float:
        return self._credits_budget - self._credits_used_locally

    def _has_budget_for(self, characters: int) -> bool:
        return self._credits_left() >= characters * self._cost_multiplier()

    def _account_spend(self, characters: int) -> None:
        self._credits_used_locally += characters * self._cost_multiplier()
        self.stats.characters_spent += characters
        self.stats.credits_estimated += characters * self._cost_multiplier()
        self._requests_since_sync += 1

        if self._requests_since_sync >= _QUOTA_RESYNC_EVERY:
            # Локальная оценка дрейфует: сверяемся с сервером, чтобы не уйти
            # в минус и не остановиться раньше времени.
            try:
                self._sync_subscription()
            except ElevenLabsError as exc:
                log.debug("Сверка остатка не удалась (%s), продолжаю по локальной оценке", exc)
                self._requests_since_sync = 0

    # ------------------------------------------------------------------
    def _voices_from_account(self) -> List[VoiceRef]:
        """Взять готовые голоса из личного кабинета вместо создания новых.

        Единственный рабочий путь на бесплатном тарифе: слоты для голосов там
        есть, но заполняются только через сайт, а создание через API отклоняют.
        """
        assert self._client is not None
        available = self._client.account_voices()
        if not available:
            raise PreflightError(
                "В аккаунте нет ни одного голоса. Создайте их на сайте ElevenLabs: "
                "Voices — My Voices — Add a new voice — Voice Design."
            )

        wanted = self.settings.selected_voice_ids
        if wanted:
            by_id = {v.voice_id: v for v in available}
            chosen = [by_id[v] for v in wanted if v in by_id]
            missing = [v for v in wanted if v not in by_id]
            if missing:
                log.warning("Выбранные голоса пропали из аккаунта и пропущены: %s", ", ".join(missing))
        else:
            # Ничего не отмечено — берём свои созданные, а не всю библиотеку.
            chosen = [v for v in available if v.is_custom] or available
            log.info("Голоса не выбраны, беру все свои: %d шт.", len(chosen))

        if not chosen:
            raise PreflightError(
                "Ни один из выбранных голосов не найден в аккаунте. "
                "Обновите список голосов в настройках и отметьте нужные."
            )

        chosen = chosen[: self.settings.max_voices]
        log.info("Использую голоса из аккаунта: %s", ", ".join(v.name for v in chosen))
        self.stats.voices_reused = len(chosen)

        return [
            VoiceRef(voice_id=v.voice_id, name=v.name, prompt_file="(из аккаунта)", reused=True)
            for v in chosen
        ]

    def _prepare_voices(self, prompts: Sequence[PromptSpec], output_dir: Path) -> List[VoiceRef]:
        assert self._client is not None
        settings = self.settings

        # None означает «проверить не удалось», пустое множество — «в аккаунте
        # голосов нет». Смешивать эти случаи нельзя: в первом надо доверять
        # кэшу, во втором — создавать голоса заново.
        existing_ids: Optional[set] = None
        try:
            existing_ids = {v.get("voice_id") for v in self._client.list_voices()}
        except ElevenLabsError as exc:
            log.warning("Не удалось получить список голосов аккаунта (%s), полагаюсь на локальный кэш", exc)

        previews_dir = output_dir / "_voices"
        voices: List[VoiceRef] = []

        for prompt in prompts:
            self._check_cancelled()
            prompt_key = digest(
                prompt.description,
                settings.voice_design_model,
                settings.guidance_scale,
                "auto" if settings.auto_generate_preview else settings.preview_text,
            )

            cached = self.state.get_voice(prompt_key)
            if cached and not settings.recreate_voices:
                if existing_ids is not None and cached.voice_id not in existing_ids:
                    log.warning(
                        "Голос «%s» пропал из аккаунта (удалён на сайте?), создам заново",
                        cached.voice_name,
                    )
                    self.state.forget_voice(prompt_key)
                else:
                    log.info("Голос «%s» уже создан, использую его", cached.voice_name)
                    voices.append(
                        VoiceRef(
                            voice_id=cached.voice_id,
                            name=cached.voice_name,
                            prompt_file=cached.prompt_file,
                            reused=True,
                        )
                    )
                    self.stats.voices_reused += 1
                    continue

            if cached and settings.recreate_voices:
                # Слоты голосов ограничены: перед пересозданием освобождаем свой.
                log.info("Пересоздаю голос «%s», удаляю прежний", cached.voice_name)
                try:
                    self._client.delete_voice(cached.voice_id)
                except ElevenLabsError as exc:
                    log.warning("Не удалось удалить прежний голос (%s), продолжаю", exc)
                self.state.forget_voice(prompt_key)

            voice = self._create_voice(prompt, prompt_key, previews_dir)
            if voice:
                voices.append(voice)

        return voices

    def _create_voice(self, prompt: PromptSpec, prompt_key: str, previews_dir: Path) -> Optional[VoiceRef]:
        assert self._client is not None
        settings = self.settings

        self._ensure_voice_slot()

        preview_cost = 0 if settings.auto_generate_preview else len(settings.preview_text)
        if preview_cost and not self._has_budget_for(preview_cost):
            raise QuotaExceeded(
                f"На создание голоса «{prompt.name}» не хватает кредитов "
                f"(нужно около {preview_cost}, доступно {self._credits_left():.0f})"
            )

        log.info("Создаю голос «%s» по промпту %s", prompt.name, prompt.path.name)
        self._progress(f"Создаю голос «{prompt.name}»")

        previews = self._client.design_voice(
            prompt.description,
            model_id=settings.voice_design_model,
            preview_text=None if settings.auto_generate_preview else settings.preview_text,
            auto_generate_text=settings.auto_generate_preview,
            guidance_scale=settings.guidance_scale,
            output_format=settings.output_format if settings.output_format.startswith("mp3") else "mp3_44100_128",
        )
        self._account_spend(preview_cost)
        self.state.log_usage("voice_design", preview_cost, note=prompt.name)

        saved_preview = self._save_previews(previews, prompt.name, previews_dir)

        chosen = previews[0]
        others = [p.generated_voice_id for p in previews[1:]]

        try:
            created = self._client.create_voice_from_preview(
                voice_name=audio_utils.safe_filename(prompt.name, max_length=60) or prompt.name,
                voice_description=prompt.description,
                generated_voice_id=chosen.generated_voice_id,
                played_not_selected=others,
                labels={"source": "elevenlabs-voiceover"},
            )
        except VoiceLimitReached:
            raise
        except ValidationFailed as exc:
            log.error("Голос «%s» не создан: %s", prompt.name, exc)
            self.stats.failures.append(f"Голос {prompt.name}: {exc}")
            return None

        voice_id = str(created.get("voice_id"))
        voice_name = str(created.get("name") or prompt.name)
        log.info("Голос «%s» создан, id %s", voice_name, voice_id)

        self.state.save_voice(
            StoredVoice(
                prompt_key=prompt_key,
                prompt_file=prompt.path.name,
                voice_id=voice_id,
                voice_name=voice_name,
                description=prompt.description,
                generated_voice_id=chosen.generated_voice_id,
                preview_path=str(saved_preview) if saved_preview else None,
            )
        )
        self.stats.voices_created += 1
        return VoiceRef(voice_id=voice_id, name=voice_name, prompt_file=prompt.path.name, reused=False)

    def _ensure_voice_slot(self) -> None:
        """Убедиться, что есть куда сохранить новый голос.

        Считаем по снимку подписки минус созданное в этом прогоне, и только при
        нехватке идём на сервер: снимок мог устареть, а лишний запрос на каждый
        голос ни к чему.
        """
        subscription = self._subscription
        if not subscription or not subscription.voice_limit:
            return

        if self._voice_slots_baseline is None:
            self._voice_slots_baseline = subscription.voice_slots_left
        if self._voice_slots_baseline - self.stats.voices_created > 0:
            return

        try:
            subscription = self._client.get_subscription() if self._client else subscription
        except ElevenLabsError as exc:
            log.debug("Не удалось обновить сведения о слотах (%s), полагаюсь на снимок", exc)
        else:
            self._subscription = subscription
            self._voice_slots_baseline = subscription.voice_slots_left + self.stats.voices_created

        if subscription.voice_slots_left <= 0:
            raise VoiceLimitReached(
                f"Свободных слотов для голосов нет ({subscription.voice_slots_used} из "
                f"{subscription.voice_limit}). Удалите лишние голоса в личном кабинете "
                "или включите «Пересоздавать голоса»."
            )

    def _save_previews(self, previews, prompt_name: str, previews_dir: Path) -> Optional[Path]:
        """Сложить все варианты голоса на диск, чтобы их можно было послушать."""
        folder = previews_dir / audio_utils.safe_filename(prompt_name, max_length=60)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("Не удалось создать папку для превью (%s)", exc)
            return None

        first: Optional[Path] = None
        for index, preview in enumerate(previews, start=1):
            if not preview.audio:
                continue
            target = folder / f"variant_{index}.mp3"
            try:
                target.write_bytes(preview.audio)
            except OSError as exc:
                log.warning("Не удалось сохранить превью %s (%s)", target.name, exc)
                continue
            if first is None:
                first = target
        if first:
            log.info("Варианты голоса «%s» сохранены в %s (используется variant_1)", prompt_name, folder)
        return first

    # ------------------------------------------------------------------
    def _build_jobs(self, texts: Sequence[TextSpec], voices: Sequence[VoiceRef], output_dir: Path) -> List[Job]:
        jobs: List[Job] = []
        used_paths: Dict[str, int] = {}
        extension = audio_utils.extension_for(self.settings.output_format)
        all_voices = self.settings.voice_mode == MODE_ALL_VOICES
        beside = self.settings.save_next_to_texts

        for index, text in enumerate(texts):
            targets = voices if all_voices else [voices[index % len(voices)]]
            for voice in targets:
                if beside:
                    # Имя исходного файла уже существует на диске, значит оно
                    # заведомо допустимо: чистить его не нужно и нельзя, иначе
                    # оно перестанет совпадать с текстом.
                    folder = text.path.parent
                    stem = text.path.stem
                else:
                    folder = output_dir
                    stem = audio_utils.safe_filename(text.name)

                if all_voices:
                    stem = f"{stem}__{audio_utils.safe_filename(voice.name, max_length=40)}"

                # Разные исходные файлы могут дать одно и то же имя результата.
                key = str(folder / stem).lower()
                count = used_paths.get(key, 0)
                used_paths[key] = count + 1
                if count:
                    stem = f"{stem}_{count + 1}"

                jobs.append(Job(text=text, voice=voice, output_path=folder / f"{stem}{extension}"))

        return jobs

    # ------------------------------------------------------------------
    def _process_job(self, job: Job) -> None:
        settings = self.settings
        params_key = digest(
            settings.model_id,
            settings.output_format,
            settings.language_code,
            tuple(sorted(settings.voice_settings_payload().items())),
        )
        text_hash = digest(job.text.text)
        output_key = digest(job.text.name, text_hash, job.voice.voice_id, params_key)

        existing = self.state.output_is_done(output_key)
        if existing:
            log.info("«%s» уже озвучен голосом «%s», пропускаю", job.text.name, job.voice.name)
            self.stats.texts_skipped += 1
            self._done_units += len(job.text.chunks)
            self._progress(f"Пропущен «{job.text.name}» (уже готов)")
            return

        chunks_dir = job.output_path.parent / "_chunks" / job.output_path.stem
        chunks_dir.mkdir(parents=True, exist_ok=True)

        total = len(job.text.chunks)
        parts: List[Path] = []
        previous_request_ids: List[str] = []

        for chunk in job.text.chunks:
            self._check_cancelled()

            task_key = digest(text_hash, job.voice.voice_id, params_key, chunk.index, digest(chunk.text))
            cached_path = self.state.chunk_is_done(task_key)
            if cached_path:
                parts.append(Path(cached_path))
                request_id = self.state.get_chunk_request_id(task_key)
                if request_id:
                    previous_request_ids.append(request_id)
                    del previous_request_ids[:-3]
                self.stats.chunks_reused += 1
                self._done_units += 1
                self._progress(f"«{job.text.name}»: кусок {chunk.index + 1}/{total} уже готов")
                continue

            if not self._has_budget_for(chunk.characters):
                self.stats.stopped_reason = "Кредиты закончились"
                log.warning(
                    "Кредитов не хватает на кусок %d/%d файла «%s» — останавливаюсь",
                    chunk.index + 1,
                    total,
                    job.text.name,
                )
                self._cleanup_incomplete(job, parts)
                raise QuotaExceeded("Доступные кредиты исчерпаны")

            self._progress(
                f"«{job.text.name}» голосом «{job.voice.name}»: кусок {chunk.index + 1}/{total}"
            )

            try:
                result = self._client.text_to_speech(  # type: ignore[union-attr]
                    job.voice.voice_id,
                    chunk.text,
                    model_id=settings.model_id,
                    output_format=settings.output_format,
                    voice_settings=settings.voice_settings_payload(),
                    previous_text=self._previous_text(job.text.chunks, chunk.index),
                    next_text=self._next_text(job.text.chunks, chunk.index),
                    previous_request_ids=list(previous_request_ids),
                    language_code=settings.language_code or None,
                )
            except ValidationFailed as exc:
                log.error("Кусок %d файла «%s» отклонён: %s", chunk.index + 1, job.text.name, exc)
                self.state.mark_chunk_failed(
                    task_key,
                    text_file=job.text.name,
                    voice_id=job.voice.voice_id,
                    chunk_index=chunk.index,
                    characters=chunk.characters,
                    error=str(exc),
                )
                self.stats.texts_failed += 1
                self.stats.failures.append(f"{job.text.name} (кусок {chunk.index + 1}): {exc}")
                self._done_units += total - chunk.index
                return

            chunk_path = chunks_dir / f"chunk_{chunk.index + 1:04d}{audio_utils.extension_for(settings.output_format)}"
            chunk_path.write_bytes(result.audio)

            self.state.mark_chunk_done(
                task_key,
                text_file=job.text.name,
                voice_id=job.voice.voice_id,
                chunk_index=chunk.index,
                characters=chunk.characters,
                audio_path=str(chunk_path),
                request_id=result.request_id,
            )
            self.state.log_usage("tts", chunk.characters, job.voice.voice_id, job.text.name)
            self._account_spend(chunk.characters)

            parts.append(chunk_path)
            if result.request_id:
                # API берёт не больше трёх, а документ может быть на сотни кусков.
                previous_request_ids.append(result.request_id)
                del previous_request_ids[:-3]
            self.stats.chunks_done += 1
            self._done_units += 1

            if settings.pause_between_requests > 0:
                self._sleep(settings.pause_between_requests)

        try:
            audio_utils.concat_audio(
                parts,
                job.output_path,
                output_format=settings.output_format,
                use_ffmpeg=settings.use_ffmpeg,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("Не удалось собрать «%s»: %s", job.output_path.name, exc)
            self.stats.texts_failed += 1
            self.stats.failures.append(f"{job.text.name}: склейка не удалась — {exc}")
            return

        self.state.mark_output_done(
            output_key,
            text_file=job.text.name,
            voice_id=job.voice.voice_id,
            voice_name=job.voice.name,
            output_path=str(job.output_path),
            characters=job.text.characters,
        )
        self.stats.texts_done += 1
        job.duration = self._measure(job.output_path)
        if job.duration:
            self.stats.seconds_produced += job.duration

        pace = _pace(job.text.characters, job.duration)
        log.info(
            "Готово: %s (голос «%s», %d символов, %s%s)",
            job.output_path.name,
            job.voice.name,
            job.text.characters,
            audio_utils.format_duration(job.duration) or "длительность не определена",
            f", {pace:.1f} симв/с" if pace else "",
        )

        if not settings.keep_chunks:
            self._remove_chunks(chunks_dir)

    @staticmethod
    def _measure(path: Path) -> Optional[float]:
        """Длительность готовой записи. Неудача измерения работе не мешает."""
        if audio_utils.format_family_of_path(path) != "mp3":
            return None
        try:
            return audio_utils.mp3_duration(path.read_bytes())
        except OSError as exc:
            log.debug("Не удалось измерить длительность %s: %s", path.name, exc)
            return None

    def _retire_source(self, text: TextSpec, jobs_for_text: Sequence[Job]) -> None:
        """Убрать исходный текст, когда все его озвучки готовы.

        Проверяем именно наличие файлов на диске, а не отметки в базе: удалять
        чужие данные можно только увидев результат своими глазами.
        """
        action = self.settings.done_action
        if action == DONE_KEEP:
            return

        if not all(job.output_path.exists() and job.output_path.stat().st_size > 0
                   for job in jobs_for_text):
            return
        if not text.path.exists():
            return

        try:
            if action == DONE_DELETE:
                text.path.unlink()
                log.info("Исходный текст удалён: %s", text.path.name)
            else:
                target = self._move_target(text.path)
                text.path.rename(target)
                log.info("Исходный текст перенесён в «%s»: %s", DONE_FOLDER_NAME, target.name)
        except OSError as exc:
            log.warning("Не удалось убрать исходный текст %s: %s", text.path.name, exc)
            self.stats.failures.append(f"{text.name}: не удалось убрать исходник — {exc}")

    @staticmethod
    def _move_target(source: Path) -> Path:
        """Свободное имя в подпапке для озвученных текстов."""
        folder = source.parent / DONE_FOLDER_NAME
        folder.mkdir(parents=True, exist_ok=True)

        target = folder / source.name
        counter = 2
        while target.exists():
            target = folder / f"{source.stem}_{counter}{source.suffix}"
            counter += 1
        return target

    @staticmethod
    def _previous_text(chunks: Sequence[Chunk], index: int) -> Optional[str]:
        """Хвост предыдущего куска как контекст для текущего.

        API использует его только для сохранения интонации на стыке: этот текст
        не озвучивается и кредиты за него не списываются.
        """
        if index <= 0:
            return None
        return chunks[index - 1].text[-_CONTEXT_CHARS:]

    @staticmethod
    def _next_text(chunks: Sequence[Chunk], index: int) -> Optional[str]:
        """Начало следующего куска как контекст для текущего."""
        if index + 1 >= len(chunks):
            return None
        return chunks[index + 1].text[:_CONTEXT_CHARS]

    def _sleep(self, seconds: float) -> None:
        if self.cancel.wait(seconds):
            raise Cancelled()

    def _cleanup_incomplete(self, job: Job, parts: Sequence[Path]) -> None:
        log.info(
            "«%s» останется незавершённым: %d из %d кусков готово, они сохранены для продолжения",
            job.text.name,
            len(parts),
            len(job.text.chunks),
        )

    def _remove_chunks(self, chunks_dir: Path) -> None:
        try:
            for item in chunks_dir.iterdir():
                item.unlink(missing_ok=True)
            chunks_dir.rmdir()
            parent = chunks_dir.parent
            if parent.name == "_chunks" and not any(parent.iterdir()):
                parent.rmdir()
        except OSError as exc:
            log.debug("Не удалось убрать временные куски из %s (%s)", chunks_dir, exc)

    # ------------------------------------------------------------------
    def _write_manifest(self, jobs: Sequence[Job], output_dir: Path) -> None:
        """Записать, какой файл каким голосом озвучен."""
        if not jobs:
            return
        manifest = output_dir / "_manifest.csv"
        try:
            with manifest.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow(
                    ["Файл результата", "Исходный текст", "Голос", "Промпт голоса",
                     "Символов", "Длительность", "Секунд", "Символов в секунду", "Готов"]
                )
                for job in jobs:
                    ready = job.output_path.exists()
                    # У пропущенных заданий длительность ещё не измерена:
                    # берём её с диска, файл уже готов с прошлого прогона.
                    if ready and job.duration is None:
                        job.duration = self._measure(job.output_path)
                    pace = _pace(job.text.characters, job.duration)
                    writer.writerow(
                        [
                            job.output_path.name,
                            job.text.path.name,
                            job.voice.name,
                            job.voice.prompt_file,
                            job.text.characters,
                            audio_utils.format_duration(job.duration),
                            f"{job.duration:.1f}".replace(".", ",") if job.duration else "",
                            f"{pace:.1f}".replace(".", ",") if pace else "",
                            "да" if ready else "нет",
                        ]
                    )
            log.info("Список готовых файлов записан в %s", manifest.name)
        except OSError as exc:
            log.warning("Не удалось записать манифест (%s)", exc)


# ----------------------------------------------------------------------
def estimate_plan(settings: Settings) -> Dict[str, object]:
    """Оценить объём работы без обращения к API и без чтения текстов.

    Тексты не открываются: в папке их может быть очень много, а разбор
    содержимого до запуска ничего не даёт — озвучка всё равно прочитает
    каждый файл в свой черёд.
    """
    prompts_dir = Path(settings.prompts_dir) if settings.prompts_dir else None
    texts_dir = Path(settings.texts_dir) if settings.texts_dir else None

    prompt_files = list_txt_files(prompts_dir) if prompts_dir else []
    text_count = count_txt_files(texts_dir) if texts_dir else 0

    from_account = settings.voice_source == SOURCE_ACCOUNT
    if from_account:
        # Голоса уже существуют: их количество известно из выбранных в настройках.
        voices = min(len(settings.selected_voice_ids) or settings.max_voices, settings.max_voices)
    else:
        voices = min(len(prompt_files), settings.max_voices)

    outputs = text_count
    if settings.voice_mode == MODE_ALL_VOICES and voices:
        outputs *= voices

    if from_account or settings.auto_generate_preview:
        design_cost = 0
    else:
        design_cost = len(settings.preview_text) * max(0, voices)

    return {
        "prompts": len(prompt_files),
        "voices": voices,
        "texts": text_count,
        "outputs": outputs,
        "line_breaks": 0,
        "chunks": 0,
        "characters": 0,
        "design_credits": design_cost,
        "total_credits_multilingual": design_cost,
        "total_credits_flash": design_cost,
    }
