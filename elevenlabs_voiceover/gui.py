"""Окно программы."""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    BooleanVar,
    Canvas,
    DoubleVar,
    IntVar,
    StringVar,
    Tk,
    X,
    Y,
    filedialog,
    messagebox,
    scrolledtext,
    ttk,
)
from typing import Any, List, Optional

from . import clipboard, diagnostics
from .api_client import ModelInfo, verify_key
from .audio import find_ffmpeg
from .config import (
    DEFAULT_GUIDANCE,
    MODE_ALL_VOICES,
    MODE_ROUND_ROBIN,
    VOICE_MODES,
    Settings,
)
from .errors import ElevenLabsError
from .logging_setup import add_gui_handler, get_logger, register_secret, setup_logging
from .paths import logs_dir
from .runner import PreflightError, Runner, estimate_plan
from .state import StateStore

log = get_logger("gui")

APP_TITLE = "Озвучка ElevenLabs"

#: Показываем до проверки ключа; после проверки список приходит из API.
FALLBACK_MODELS = [
    "eleven_flash_v2_5",
    "eleven_turbo_v2_5",
    "eleven_multilingual_v2",
    "eleven_v3",
]

OUTPUT_FORMATS = [
    "mp3_44100_128",
    "mp3_44100_192",
    "mp3_44100_96",
    "mp3_44100_64",
    "mp3_44100_32",
    "mp3_22050_32",
]

VOICE_DESIGN_MODELS = ["eleven_multilingual_ttv_v2", "eleven_ttv_v3"]

MAX_LOG_LINES = 2000


class App:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.settings = Settings.load()
        self.state = StateStore()

        self.events: queue.Queue[tuple] = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: Optional[threading.Thread] = None
        self.models: List[ModelInfo] = []

        self._build_ui()
        self._settings_to_widgets()

        self.log_handler = add_gui_handler(self._enqueue_log)
        self.root.after(100, self._drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        register_secret(self.settings.api_key)
        self._refresh_estimate()
        self._report_ffmpeg()

    # ==================================================================
    # Построение интерфейса
    # ==================================================================
    def _build_ui(self) -> None:
        self.root.title(APP_TITLE)
        self.root.geometry("980x760")
        self.root.minsize(860, 640)

        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Hint.TLabel", foreground="#555555")
        style.configure("Good.TLabel", foreground="#146b2e")
        style.configure("Bad.TLabel", foreground="#a11")
        style.configure("Head.TLabel", font=("Segoe UI", 10, "bold"))

        # Нижнюю панель размещаем первой: в pack приоритет у того, кто раньше,
        # а кнопки «Начать» и «Остановить» должны быть видны всегда, даже если
        # содержимое вкладки выше окна.
        self._build_bottom(self.root)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=BOTH, expand=True, padx=10, pady=(10, 0), side="top")

        self.tab_work = ttk.Frame(self.notebook, padding=12)
        self.tab_settings = ttk.Frame(self.notebook)
        self.tab_log = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.tab_work, text="  Работа  ")
        self.notebook.add(self.tab_settings, text="  Настройки  ")
        self.notebook.add(self.tab_log, text="  Журнал  ")

        self._build_work_tab(self.tab_work)
        self._build_settings_tab(_scrollable(self.tab_settings))
        self._build_log_tab(self.tab_log)
        self._enable_clipboard()

    def _enable_clipboard(self) -> None:
        """Оживить работу с буфером во всех полях окна.

        Обходим дерево виджетов, а не перечисляем поля руками: иначе про
        очередное добавленное поле легко забыть, и оно снова окажется без
        вставки по правой кнопке.
        """
        clipboard.install_shortcuts(self.root)

        for widget in _all_widgets(self.root):
            if isinstance(widget, tk.Entry):
                clipboard.attach_context_menu(widget)
            elif isinstance(widget, tk.Text):
                editable = str(widget.cget("state")) != "disabled"
                clipboard.attach_context_menu(widget, editable=editable)

    # ------------------------------------------------------------------
    def _build_work_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        row = 0

        ttk.Label(parent, text="Доступ к ElevenLabs", style="Head.TLabel").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )
        row += 1

        ttk.Label(parent, text="API-ключ:").grid(row=row, column=0, sticky="w", pady=3)
        key_frame = ttk.Frame(parent)
        key_frame.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        key_frame.columnconfigure(0, weight=1)

        self.var_api_key = StringVar()
        self.entry_key = ttk.Entry(key_frame, textvariable=self.var_api_key, show="\u2022")
        self.entry_key.grid(row=0, column=0, sticky="ew")

        ttk.Button(key_frame, text="Вставить", width=10, command=self._paste_key).grid(
            row=0, column=1, padx=(6, 0)
        )

        self.var_show_key = BooleanVar(value=False)
        ttk.Checkbutton(
            key_frame, text="показать", variable=self.var_show_key, command=self._toggle_key_visibility
        ).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(key_frame, text="Проверить", command=self._verify_key).grid(row=0, column=3, padx=(8, 0))
        row += 1

        ttk.Label(
            parent,
            text="Ключ можно вставить кнопкой, сочетанием Ctrl+V или правой кнопкой мыши по полю",
            style="Hint.TLabel",
        ).grid(row=row, column=1, columnspan=2, sticky="w")
        row += 1

        self.var_remember_key = BooleanVar(value=True)
        ttk.Checkbutton(
            parent, text="Запомнить ключ на этом компьютере", variable=self.var_remember_key
        ).grid(row=row, column=1, sticky="w")
        row += 1

        self.lbl_account = ttk.Label(parent, text="Ключ ещё не проверен", style="Hint.TLabel")
        self.lbl_account.grid(row=row, column=1, columnspan=2, sticky="w", pady=(2, 10))
        row += 1

        ttk.Separator(parent, orient="horizontal").grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)
        row += 1

        ttk.Label(parent, text="Папки", style="Head.TLabel").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )
        row += 1

        self.var_prompts_dir = StringVar()
        self.var_texts_dir = StringVar()
        self.var_output_dir = StringVar()

        row = self._folder_row(parent, row, "Промпты голосов:", self.var_prompts_dir,
                               "Папка с .txt, в каждом — описание одного голоса")
        row = self._folder_row(parent, row, "Тексты для озвучки:", self.var_texts_dir,
                               "Папка с .txt, каждый файл станет отдельной озвучкой")
        row = self._folder_row(parent, row, "Куда сохранять:", self.var_output_dir,
                               "Готовые файлы, превью голосов и список _manifest.csv")

        ttk.Separator(parent, orient="horizontal").grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)
        row += 1

        ttk.Label(parent, text="Порядок работы", style="Head.TLabel").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )
        row += 1

        ttk.Label(parent, text="Голосов создать:").grid(row=row, column=0, sticky="w", pady=3)
        self.var_max_voices = IntVar(value=3)
        ttk.Spinbox(parent, from_=1, to=50, width=6, textvariable=self.var_max_voices,
                    command=self._refresh_estimate).grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        ttk.Label(parent, text="Раздача голосов:").grid(row=row, column=0, sticky="w", pady=3)
        self.var_voice_mode = StringVar(value=VOICE_MODES[MODE_ROUND_ROBIN])
        combo_mode = ttk.Combobox(
            parent, textvariable=self.var_voice_mode, state="readonly",
            values=[VOICE_MODES[MODE_ROUND_ROBIN], VOICE_MODES[MODE_ALL_VOICES]],
        )
        combo_mode.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        combo_mode.bind("<<ComboboxSelected>>", lambda _e: self._refresh_estimate())
        row += 1

        self.var_recreate = BooleanVar(value=False)
        ttk.Checkbutton(
            parent,
            text="Пересоздать голоса заново (удалит прежние и потратит кредиты)",
            variable=self.var_recreate,
        ).grid(row=row, column=1, columnspan=2, sticky="w", pady=(2, 6))
        row += 1

        ttk.Separator(parent, orient="horizontal").grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)
        row += 1

        self.lbl_estimate = ttk.Label(
            parent, text="Укажите папки, чтобы увидеть оценку", style="Hint.TLabel",
            justify=LEFT, wraplength=880,
        )
        self.lbl_estimate.grid(row=row, column=0, columnspan=3, sticky="w")
        parent.rowconfigure(row + 1, weight=1)

    def _folder_row(
        self, parent: ttk.Frame, row: int, label: str, variable: StringVar, hint: str
    ) -> int:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        variable.trace_add("write", lambda *_: self._refresh_estimate())

        buttons = ttk.Frame(parent)
        buttons.grid(row=row, column=2, sticky="w", padx=(8, 0))
        ttk.Button(buttons, text="Обзор…", width=9,
                   command=lambda v=variable: self._pick_folder(v)).pack(side=LEFT)
        ttk.Button(buttons, text="Открыть", width=9,
                   command=lambda v=variable: self._open_path(v.get())).pack(side=LEFT, padx=(4, 0))

        ttk.Label(parent, text=hint, style="Hint.TLabel").grid(
            row=row + 1, column=1, columnspan=2, sticky="w", pady=(0, 6)
        )
        return row + 2

    # ------------------------------------------------------------------
    def _build_settings_tab(self, parent: ttk.Frame) -> None:
        canvas_frame = ttk.Frame(parent)
        canvas_frame.pack(fill=BOTH, expand=True)
        canvas_frame.columnconfigure(1, weight=1)
        row = 0

        ttk.Label(canvas_frame, text="Озвучка", style="Head.TLabel").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )
        row += 1

        ttk.Label(canvas_frame, text="Модель:").grid(row=row, column=0, sticky="w", pady=3)
        self.var_model = StringVar(value="eleven_flash_v2_5")
        self.combo_model = ttk.Combobox(canvas_frame, textvariable=self.var_model, values=FALLBACK_MODELS)
        self.combo_model.grid(row=row, column=1, sticky="ew", pady=3)
        self.combo_model.bind("<<ComboboxSelected>>", lambda _e: self._refresh_estimate())
        ttk.Label(canvas_frame, text="Flash дешевле вдвое", style="Hint.TLabel").grid(
            row=row, column=2, sticky="w", padx=(8, 0)
        )
        row += 1

        ttk.Label(canvas_frame, text="Формат файла:").grid(row=row, column=0, sticky="w", pady=3)
        self.var_output_format = StringVar(value="mp3_44100_128")
        ttk.Combobox(canvas_frame, textvariable=self.var_output_format, values=OUTPUT_FORMATS,
                     state="readonly").grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Label(canvas_frame, text="192 кбит/с — от тарифа Creator", style="Hint.TLabel").grid(
            row=row, column=2, sticky="w", padx=(8, 0)
        )
        row += 1

        ttk.Label(canvas_frame, text="Символов в куске:").grid(row=row, column=0, sticky="w", pady=3)
        self.var_chunk = IntVar(value=2500)
        ttk.Spinbox(canvas_frame, from_=200, to=40000, increment=100, width=10,
                    textvariable=self.var_chunk, command=self._refresh_estimate).grid(
            row=row, column=1, sticky="w", pady=3
        )
        ttk.Label(canvas_frame, text="Меньше — надёжнее при обрывах", style="Hint.TLabel").grid(
            row=row, column=2, sticky="w", padx=(8, 0)
        )
        row += 1

        ttk.Label(canvas_frame, text="Код языка:").grid(row=row, column=0, sticky="w", pady=3)
        self.var_language = StringVar(value="")
        ttk.Entry(canvas_frame, textvariable=self.var_language, width=10).grid(
            row=row, column=1, sticky="w", pady=3
        )
        ttk.Label(canvas_frame, text="Пусто — определить автоматически (ru, en, …)",
                  style="Hint.TLabel").grid(row=row, column=2, sticky="w", padx=(8, 0))
        row += 1

        row = self._separator(canvas_frame, row, "Параметры голоса")

        self.var_stability = DoubleVar(value=0.5)
        self.var_similarity = DoubleVar(value=0.75)
        self.var_style = DoubleVar(value=0.0)
        self.var_speed = DoubleVar(value=1.0)

        row = self._scale_row(canvas_frame, row, "Стабильность:", self.var_stability, 0.0, 1.0,
                              "Ниже — больше эмоций, выше — ровнее")
        row = self._scale_row(canvas_frame, row, "Схожесть:", self.var_similarity, 0.0, 1.0,
                              "Насколько строго держаться исходного тембра")
        row = self._scale_row(canvas_frame, row, "Выразительность:", self.var_style, 0.0, 1.0,
                              "Выше нуля — медленнее генерация")
        row = self._scale_row(canvas_frame, row, "Скорость речи:", self.var_speed, 0.5, 2.0,
                              "1.0 — обычный темп")

        self.var_speaker_boost = BooleanVar(value=True)
        ttk.Checkbutton(canvas_frame, text="Speaker boost (точнее тембр, чуть медленнее)",
                        variable=self.var_speaker_boost).grid(
            row=row, column=1, columnspan=2, sticky="w", pady=3
        )
        row += 1

        row = self._separator(canvas_frame, row, "Создание голосов")

        ttk.Label(canvas_frame, text="Модель Voice Design:").grid(row=row, column=0, sticky="w", pady=3)
        self.var_design_model = StringVar(value="eleven_multilingual_ttv_v2")
        ttk.Combobox(canvas_frame, textvariable=self.var_design_model, values=VOICE_DESIGN_MODELS,
                     state="readonly").grid(row=row, column=1, sticky="ew", pady=3)
        row += 1

        ttk.Label(canvas_frame, text="Точность промпта:").grid(row=row, column=0, sticky="w", pady=3)
        self.var_guidance = DoubleVar(value=DEFAULT_GUIDANCE)
        ttk.Spinbox(canvas_frame, from_=0.0, to=100.0, increment=5.0, width=10,
                    textvariable=self.var_guidance).grid(row=row, column=1, sticky="w", pady=3)
        ttk.Label(canvas_frame, text="Шкала 0–100. Выше — строже по промпту, но звук искусственнее",
                  style="Hint.TLabel").grid(row=row, column=2, sticky="w", padx=(8, 0))
        row += 1
        ttk.Label(
            canvas_frame,
            text=f"По умолчанию в API стоит {DEFAULT_GUIDANCE:g} — это очень творческий край шкалы. "
                 "В примерах ElevenLabs используют 25–40: начните оттуда, если голос "
                 "получается непохожим на описание.",
            style="Hint.TLabel", justify=LEFT, wraplength=700,
        ).grid(row=row, column=1, columnspan=2, sticky="w", pady=(0, 6))
        row += 1

        self.var_auto_preview = BooleanVar(value=False)
        ttk.Checkbutton(
            canvas_frame,
            text="Пусть ElevenLabs сам придумает текст для прослушивания голоса",
            variable=self.var_auto_preview,
            command=self._refresh_estimate,
        ).grid(row=row, column=1, columnspan=2, sticky="w", pady=3)
        row += 1

        ttk.Label(canvas_frame, text="Текст прослушивания:").grid(row=row, column=0, sticky="nw", pady=3)
        self.txt_preview = scrolledtext.ScrolledText(canvas_frame, height=4, wrap="word")
        self.txt_preview.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        row += 1
        ttk.Label(canvas_frame,
                  text="Именно за его длину списываются кредиты при создании голоса (100–1000 символов)",
                  style="Hint.TLabel").grid(row=row, column=1, columnspan=2, sticky="w", pady=(0, 6))
        row += 1

        row = self._separator(canvas_frame, row, "Бюджет и надёжность")

        ttk.Label(canvas_frame, text="Оставить в запасе:").grid(row=row, column=0, sticky="w", pady=3)
        self.var_reserve = IntVar(value=0)
        ttk.Spinbox(canvas_frame, from_=0, to=10_000_000, increment=500, width=12,
                    textvariable=self.var_reserve).grid(row=row, column=1, sticky="w", pady=3)
        ttk.Label(canvas_frame, text="кредитов, которые программа не потратит",
                  style="Hint.TLabel").grid(row=row, column=2, sticky="w", padx=(8, 0))
        row += 1

        ttk.Label(canvas_frame, text="Пауза между запросами:").grid(row=row, column=0, sticky="w", pady=3)
        self.var_pause = DoubleVar(value=0.4)
        ttk.Spinbox(canvas_frame, from_=0.0, to=60.0, increment=0.1, width=12,
                    textvariable=self.var_pause).grid(row=row, column=1, sticky="w", pady=3)
        ttk.Label(canvas_frame, text="секунд", style="Hint.TLabel").grid(
            row=row, column=2, sticky="w", padx=(8, 0)
        )
        row += 1

        ttk.Label(canvas_frame, text="Повторов при сбое:").grid(row=row, column=0, sticky="w", pady=3)
        self.var_retries = IntVar(value=5)
        ttk.Spinbox(canvas_frame, from_=0, to=20, width=12, textvariable=self.var_retries).grid(
            row=row, column=1, sticky="w", pady=3
        )
        row += 1

        ttk.Label(canvas_frame, text="Таймаут запроса:").grid(row=row, column=0, sticky="w", pady=3)
        self.var_timeout = IntVar(value=180)
        ttk.Spinbox(canvas_frame, from_=10, to=3600, increment=10, width=12,
                    textvariable=self.var_timeout).grid(row=row, column=1, sticky="w", pady=3)
        ttk.Label(canvas_frame, text="секунд", style="Hint.TLabel").grid(
            row=row, column=2, sticky="w", padx=(8, 0)
        )
        row += 1

        self.var_keep_chunks = BooleanVar(value=False)
        ttk.Checkbutton(canvas_frame, text="Не удалять промежуточные куски после склейки",
                        variable=self.var_keep_chunks).grid(
            row=row, column=1, columnspan=2, sticky="w", pady=3
        )
        row += 1

        self.var_use_ffmpeg = BooleanVar(value=True)
        ttk.Checkbutton(canvas_frame, text="Склеивать через ffmpeg, если он найден",
                        variable=self.var_use_ffmpeg).grid(
            row=row, column=1, columnspan=2, sticky="w", pady=3
        )
        row += 1

        self.lbl_ffmpeg = ttk.Label(canvas_frame, text="", style="Hint.TLabel")
        self.lbl_ffmpeg.grid(row=row, column=1, columnspan=2, sticky="w")

    def _separator(self, parent: ttk.Frame, row: int, title: str) -> int:
        ttk.Separator(parent, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=(12, 8)
        )
        ttk.Label(parent, text=title, style="Head.TLabel").grid(
            row=row + 1, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )
        return row + 2

    def _scale_row(
        self, parent: ttk.Frame, row: int, label: str, variable: DoubleVar,
        low: float, high: float, hint: str,
    ) -> int:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        holder = ttk.Frame(parent)
        holder.grid(row=row, column=1, sticky="ew", pady=3)
        holder.columnconfigure(0, weight=1)

        value_label = ttk.Label(holder, text=f"{variable.get():.2f}", width=5)
        scale = ttk.Scale(
            holder, from_=low, to=high, variable=variable, orient="horizontal",
            command=lambda v, lbl=value_label: lbl.configure(text=f"{float(v):.2f}"),
        )
        scale.grid(row=0, column=0, sticky="ew")
        value_label.grid(row=0, column=1, padx=(8, 0))

        ttk.Label(parent, text=hint, style="Hint.TLabel").grid(
            row=row, column=2, sticky="w", padx=(8, 0)
        )
        return row + 1

    # ------------------------------------------------------------------
    def _build_log_tab(self, parent: ttk.Frame) -> None:
        font = ("Consolas", 9) if sys.platform == "win32" else ("Monospace", 9)
        self.txt_log = scrolledtext.ScrolledText(parent, wrap="word", font=font, state="disabled")
        self.txt_log.pack(fill=BOTH, expand=True)

        self.txt_log.tag_configure("WARNING", foreground="#8a6d00")
        self.txt_log.tag_configure("ERROR", foreground="#a11")
        self.txt_log.tag_configure("CRITICAL", foreground="#a11")

        buttons = ttk.Frame(parent)
        buttons.pack(fill=X, pady=(8, 0))
        ttk.Button(buttons, text="Очистить окно", command=self._clear_log).pack(side=LEFT)
        ttk.Button(buttons, text="Папка с логами", command=lambda: self._open_path(str(logs_dir()))).pack(
            side=LEFT, padx=(8, 0)
        )

    # ------------------------------------------------------------------
    def _build_bottom(self, parent: Tk) -> None:
        frame = ttk.Frame(parent, padding=(10, 8, 10, 10))
        frame.pack(fill=X, side="bottom")
        frame.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=1000)
        self.progress.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 6))

        self.lbl_status = ttk.Label(frame, text="Готов к работе")
        self.lbl_status.grid(row=1, column=0, sticky="w")

        self.btn_start = ttk.Button(frame, text="Начать озвучку", command=self._start)
        self.btn_start.grid(row=1, column=1, padx=(8, 0))

        self.btn_stop = ttk.Button(frame, text="Остановить", command=self._stop, state="disabled")
        self.btn_stop.grid(row=1, column=2, padx=(8, 0))

        extras = ttk.Frame(frame)
        extras.grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))
        ttk.Button(extras, text="Собрать отчёт о проблеме", command=self._build_report).pack(side=LEFT)
        ttk.Button(extras, text="Сбросить прогресс", command=self._reset_progress).pack(side=LEFT, padx=(8, 0))
        ttk.Button(extras, text="Ключи ElevenLabs", command=self._open_keys_page).pack(side=LEFT, padx=(8, 0))

    # ==================================================================
    # Синхронизация настроек и виджетов
    # ==================================================================
    def _settings_to_widgets(self) -> None:
        s = self.settings
        self.var_api_key.set(s.api_key)
        self.var_remember_key.set(s.remember_api_key)
        self.var_prompts_dir.set(s.prompts_dir)
        self.var_texts_dir.set(s.texts_dir)
        self.var_output_dir.set(s.output_dir)
        self.var_max_voices.set(s.max_voices)
        self.var_voice_mode.set(VOICE_MODES.get(s.voice_mode, VOICE_MODES[MODE_ROUND_ROBIN]))
        self.var_recreate.set(s.recreate_voices)

        self.var_model.set(s.model_id)
        self.var_output_format.set(s.output_format)
        self.var_chunk.set(s.chunk_target_chars)
        self.var_language.set(s.language_code)

        self.var_stability.set(s.stability)
        self.var_similarity.set(s.similarity_boost)
        self.var_style.set(s.style)
        self.var_speed.set(s.speed)
        self.var_speaker_boost.set(s.use_speaker_boost)

        self.var_design_model.set(s.voice_design_model)
        self.var_guidance.set(s.guidance_scale)
        self.var_auto_preview.set(s.auto_generate_preview)
        self.txt_preview.delete("1.0", END)
        self.txt_preview.insert("1.0", s.preview_text)

        self.var_reserve.set(s.reserve_credits)
        self.var_pause.set(s.pause_between_requests)
        self.var_retries.set(s.max_retries)
        self.var_timeout.set(s.request_timeout)
        self.var_keep_chunks.set(s.keep_chunks)
        self.var_use_ffmpeg.set(s.use_ffmpeg)

    def _widgets_to_settings(self) -> Settings:
        s = self.settings
        s.api_key = self.var_api_key.get().strip()
        s.remember_api_key = bool(self.var_remember_key.get())
        s.prompts_dir = self.var_prompts_dir.get().strip()
        s.texts_dir = self.var_texts_dir.get().strip()
        s.output_dir = self.var_output_dir.get().strip()
        s.max_voices = _safe_int(self.var_max_voices, s.max_voices)
        s.voice_mode = _mode_from_label(self.var_voice_mode.get())
        s.recreate_voices = bool(self.var_recreate.get())

        s.model_id = self.var_model.get().strip() or s.model_id
        s.output_format = self.var_output_format.get().strip() or s.output_format
        s.chunk_target_chars = _safe_int(self.var_chunk, s.chunk_target_chars)
        s.language_code = self.var_language.get().strip()

        s.stability = _safe_float(self.var_stability, s.stability)
        s.similarity_boost = _safe_float(self.var_similarity, s.similarity_boost)
        s.style = _safe_float(self.var_style, s.style)
        s.speed = _safe_float(self.var_speed, s.speed)
        s.use_speaker_boost = bool(self.var_speaker_boost.get())

        s.voice_design_model = self.var_design_model.get().strip() or s.voice_design_model
        s.guidance_scale = _safe_float(self.var_guidance, s.guidance_scale)
        s.auto_generate_preview = bool(self.var_auto_preview.get())
        s.preview_text = self.txt_preview.get("1.0", END).strip()

        s.reserve_credits = _safe_int(self.var_reserve, s.reserve_credits)
        s.pause_between_requests = _safe_float(self.var_pause, s.pause_between_requests)
        s.max_retries = _safe_int(self.var_retries, s.max_retries)
        s.request_timeout = _safe_int(self.var_timeout, s.request_timeout)
        s.keep_chunks = bool(self.var_keep_chunks.get())
        s.use_ffmpeg = bool(self.var_use_ffmpeg.get())

        s.normalize()
        register_secret(s.api_key)
        return s

    # ==================================================================
    # Действия
    # ==================================================================
    def _toggle_key_visibility(self) -> None:
        self.entry_key.configure(show="" if self.var_show_key.get() else "\u2022")

    def _paste_key(self) -> None:
        """Положить ключ из буфера в поле, заменив прежнее значение."""
        text = clipboard.clipboard_text(self.root)
        if not text:
            messagebox.showinfo(
                APP_TITLE,
                "В буфере обмена пусто.\n\nСкопируйте ключ на странице ElevenLabs "
                "и нажмите «Вставить» ещё раз.",
                parent=self.root,
            )
            return

        self.var_api_key.set(text)
        self.entry_key.icursor(END)
        # Показываем вставленное: так сразу видно, что попал именно ключ,
        # а не случайно скопированный до него текст.
        self.var_show_key.set(True)
        self._toggle_key_visibility()
        log.info("Ключ вставлен из буфера обмена, длина %d символов", len(text))

    def _pick_folder(self, variable: StringVar) -> None:
        initial = variable.get() or str(Path.home())
        chosen = filedialog.askdirectory(initialdir=initial, parent=self.root)
        if chosen:
            variable.set(chosen)

    def _open_path(self, path: str) -> None:
        target = Path(path) if path else None
        if not target or not target.exists():
            messagebox.showinfo(APP_TITLE, "Папка ещё не существует.", parent=self.root)
            return
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(target)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Не удалось открыть папку:\n{exc}", parent=self.root)

    def _open_keys_page(self) -> None:
        webbrowser.open("https://elevenlabs.io/app/developers/api-keys")

    def _report_ffmpeg(self) -> None:
        found = find_ffmpeg()
        if found:
            self.lbl_ffmpeg.configure(text=f"ffmpeg найден: {found}")
        else:
            self.lbl_ffmpeg.configure(
                text="ffmpeg не найден — MP3 будут склеены встроенным способом. "
                     "Для других форматов положите ffmpeg.exe рядом с программой."
            )

    # ------------------------------------------------------------------
    def _verify_key(self) -> None:
        settings = self._widgets_to_settings()
        key = settings.resolved_api_key()
        if not key:
            messagebox.showwarning(APP_TITLE, "Сначала вставьте API-ключ.", parent=self.root)
            return

        self.lbl_account.configure(text="Проверяю ключ…", style="Hint.TLabel")
        self._set_busy(True)

        def work() -> None:
            try:
                subscription, models = verify_key(key, timeout=settings.request_timeout)
            except ElevenLabsError as exc:
                self.events.put(("verify_failed", str(exc)))
            except Exception as exc:  # noqa: BLE001
                self.events.put(("verify_failed", f"Непредвиденная ошибка: {exc}"))
            else:
                self.events.put(("verify_ok", subscription, models))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------
    def _refresh_estimate(self) -> None:
        try:
            settings = self._widgets_to_settings()
        except Exception:  # noqa: BLE001 - виджеты могли ещё не создаться
            return

        if not settings.prompts_dir or not settings.texts_dir:
            self.lbl_estimate.configure(text="Укажите папки, чтобы увидеть оценку")
            return

        try:
            plan = estimate_plan(settings)
        except Exception as exc:  # noqa: BLE001
            self.lbl_estimate.configure(text=f"Не удалось оценить объём: {exc}")
            return

        model = self.var_model.get()
        cheap = "flash" in model or "turbo" in model
        credits = plan["total_credits_flash"] if cheap else plan["total_credits_multilingual"]

        self.lbl_estimate.configure(
            text=(
                f"Найдено: промптов {plan['prompts']} (будет создано голосов {plan['voices']}), "
                f"текстов {plan['texts']}, кусков {plan['chunks']}, "
                f"символов {_fmt(plan['characters'])}.\n"
                f"Ориентировочный расход: около {_fmt(credits)} кредитов, "
                f"из них {_fmt(plan['design_credits'])} на создание голосов."
            )
        )

    # ------------------------------------------------------------------
    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        settings = self._widgets_to_settings()
        problems = _validate(settings)
        if problems:
            messagebox.showwarning(APP_TITLE, "Не хватает данных:\n\n• " + "\n• ".join(problems), parent=self.root)
            return

        if settings.recreate_voices and not messagebox.askyesno(
            APP_TITLE,
            "Включено пересоздание голосов.\n\n"
            "Прежние голоса будут удалены из аккаунта, а на новые уйдут кредиты.\n\nПродолжить?",
            parent=self.root,
        ):
            return

        try:
            settings.save()
        except OSError as exc:
            log.warning("Не удалось сохранить настройки: %s", exc)

        self.cancel_event = threading.Event()
        self._set_busy(True)
        self.progress.configure(value=0)
        self.lbl_status.configure(text="Запускаю…")
        log.info("=" * 60)
        log.info("Запуск: голосов до %d, режим «%s»", settings.max_voices, VOICE_MODES[settings.voice_mode])

        def work() -> None:
            runner = Runner(
                settings,
                self.state,
                cancel_event=self.cancel_event,
                on_progress=lambda fraction, message: self.events.put(("progress", fraction, message)),
            )
            try:
                stats = runner.run()
            except PreflightError as exc:
                self.events.put(("failed", str(exc)))
            except Exception as exc:
                log.exception("Рабочий поток упал")
                self.events.put(("failed", f"Непредвиденная ошибка: {exc}"))
            else:
                self.events.put(("finished", stats))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _stop(self) -> None:
        if self.worker and self.worker.is_alive():
            self.cancel_event.set()
            self.lbl_status.configure(text="Останавливаюсь, дожидаюсь текущего запроса…")
            self.btn_stop.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        self.btn_start.configure(state="disabled" if busy else "normal")
        self.btn_stop.configure(state="normal" if busy else "disabled")

    # ------------------------------------------------------------------
    def _reset_progress(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_TITLE, "Сначала остановите работу.", parent=self.root)
            return

        answer = messagebox.askyesnocancel(
            APP_TITLE,
            "Сбросить прогресс озвучки?\n\n"
            "Да — забыть, какие тексты уже озвучены (голоса останутся).\n"
            "Нет — забыть ещё и созданные голоса.\n"
            "Отмена — ничего не делать.\n\n"
            "Файлы на диске не удаляются, но повторная озвучка потратит кредиты заново.",
            parent=self.root,
        )
        if answer is None:
            return
        self.state.reset_progress(drop_voices=not answer)
        messagebox.showinfo(APP_TITLE, "Прогресс сброшен.", parent=self.root)

    def _build_report(self) -> None:
        try:
            settings = self._widgets_to_settings()
            path = diagnostics.build_report(settings, self.state)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Не удалось собрать отчёт:\n{exc}", parent=self.root)
            return

        if messagebox.askyesno(
            APP_TITLE,
            f"Отчёт готов:\n\n{path}\n\nAPI-ключ из него вырезан.\n\nОткрыть папку с отчётом?",
            parent=self.root,
        ):
            self._open_path(str(path.parent))

    def _clear_log(self) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", END)
        self.txt_log.configure(state="disabled")

    # ==================================================================
    # Обработка событий из рабочих потоков
    # ==================================================================
    def _enqueue_log(self, line: str, level: str) -> None:
        self.events.put(("log", line, level))

    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._drain_events)

    def _handle_event(self, event: tuple) -> None:
        kind = event[0]

        if kind == "log":
            self._append_log(event[1], event[2])
        elif kind == "progress":
            fraction, message = event[1], event[2]
            self.progress.configure(value=int(fraction * 1000))
            self.lbl_status.configure(text=message)
        elif kind == "finished":
            self._on_finished(event[1])
        elif kind == "failed":
            self._set_busy(False)
            self.lbl_status.configure(text="Остановлено из-за ошибки")
            messagebox.showerror(APP_TITLE, event[1], parent=self.root)
        elif kind == "verify_ok":
            self._set_busy(False)
            self._on_verified(event[1], event[2])
        elif kind == "verify_failed":
            self._set_busy(False)
            self.lbl_account.configure(text=f"Ключ не принят: {event[1]}", style="Bad.TLabel")
            messagebox.showerror(APP_TITLE, f"Ключ не принят.\n\n{event[1]}", parent=self.root)

    def _append_log(self, line: str, level: str) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.insert(END, line + "\n", level if level in ("WARNING", "ERROR", "CRITICAL") else "")

        # Не даём окну логов расти бесконечно за долгий прогон.
        line_count = int(self.txt_log.index("end-1c").split(".")[0])
        if line_count > MAX_LOG_LINES:
            self.txt_log.delete("1.0", f"{line_count - MAX_LOG_LINES}.0")

        self.txt_log.see(END)
        self.txt_log.configure(state="disabled")

    def _on_verified(self, subscription: Any, models: List[ModelInfo]) -> None:
        self.models = models
        tts_models = [m for m in models if m.can_do_text_to_speech]
        if tts_models:
            self.combo_model.configure(values=[m.model_id for m in tts_models])
            if self.var_model.get() not in {m.model_id for m in tts_models}:
                self.var_model.set(tts_models[0].model_id)

        warning = ""
        if subscription.voice_slots_left < self.settings.max_voices:
            warning = (
                f"  Внимание: свободных слотов голосов {subscription.voice_slots_left}, "
                f"а запрошено {self.settings.max_voices}."
            )

        self.lbl_account.configure(text=subscription.summary() + warning, style="Good.TLabel")
        log.info("Ключ проверен. %s", subscription.summary())
        self._refresh_estimate()

    def _on_finished(self, stats: Any) -> None:
        self._set_busy(False)
        self.progress.configure(value=1000 if not stats.stopped_reason else self.progress["value"])

        summary = (
            f"Готово файлов: {stats.texts_done}\n"
            f"Пропущено (уже были готовы): {stats.texts_skipped}\n"
            f"С ошибками: {stats.texts_failed}\n"
            f"Голосов создано: {stats.voices_created}, использовано готовых: {stats.voices_reused}\n"
            f"Озвучено символов: {_fmt(stats.characters_spent)}\n"
            f"Потрачено кредитов (оценка): {_fmt(stats.credits_estimated)}"
        )

        if stats.stopped_reason:
            summary += f"\n\nОстановлено: {stats.stopped_reason}"
        if stats.failures:
            summary += "\n\nОшибки:\n• " + "\n• ".join(stats.failures[:10])

        self.lbl_status.configure(text=stats.stopped_reason or "Работа завершена")
        log.info("Работа завершена")

        if stats.texts_failed or stats.stopped_reason:
            messagebox.showwarning(APP_TITLE, summary, parent=self.root)
        else:
            messagebox.showinfo(APP_TITLE, summary, parent=self.root)

    # ------------------------------------------------------------------
    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(
                APP_TITLE, "Работа ещё идёт. Остановить и выйти?", parent=self.root
            ):
                return
            self.cancel_event.set()
            self.worker.join(timeout=10)

        try:
            self._widgets_to_settings().save()
        except Exception as exc:  # noqa: BLE001
            log.warning("Настройки при выходе сохранить не удалось: %s", exc)

        self.state.close()
        self.root.destroy()


# ----------------------------------------------------------------------
def _all_widgets(root: tk.Misc):
    """Обойти дерево виджетов сверху вниз."""
    yield root
    for child in root.winfo_children():
        yield from _all_widgets(child)


def _scrollable(parent: ttk.Frame) -> ttk.Frame:
    """Обернуть вкладку в прокручиваемую область.

    Настроек много, и на ноутбучном экране они не помещаются целиком.
    """
    canvas = Canvas(parent, highlightthickness=0, borderwidth=0)
    scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    inner = ttk.Frame(canvas, padding=12)

    window = canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side=LEFT, fill=BOTH, expand=True)
    scrollbar.pack(side=RIGHT, fill=Y)

    inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))

    def on_wheel(event) -> None:
        if event.num == 5 or event.delta < 0:
            canvas.yview_scroll(1, "units")
        elif event.num == 4 or event.delta > 0:
            canvas.yview_scroll(-1, "units")

    # Колесо перехватываем только пока курсор над вкладкой, иначе оно перестанет
    # работать в других частях окна.
    def grab_wheel(_event=None) -> None:
        canvas.bind_all("<MouseWheel>", on_wheel)
        canvas.bind_all("<Button-4>", on_wheel)
        canvas.bind_all("<Button-5>", on_wheel)

    def release_wheel(_event=None) -> None:
        canvas.unbind_all("<MouseWheel>")
        canvas.unbind_all("<Button-4>")
        canvas.unbind_all("<Button-5>")

    canvas.bind("<Enter>", grab_wheel)
    canvas.bind("<Leave>", release_wheel)

    return inner


def _fmt(number: float) -> str:
    """Число с неразрывным пробелом между разрядами."""
    return f"{int(number):,}".replace(",", "\u00a0")


def _validate(settings: Settings) -> List[str]:
    problems: List[str] = []
    if not settings.resolved_api_key():
        problems.append("не указан API-ключ")
    if not settings.prompts_dir or not Path(settings.prompts_dir).is_dir():
        problems.append("не выбрана папка с промптами голосов")
    if not settings.texts_dir or not Path(settings.texts_dir).is_dir():
        problems.append("не выбрана папка с текстами")
    if not settings.output_dir:
        problems.append("не выбрана папка для результатов")
    return problems


def _mode_from_label(label: str) -> str:
    for key, value in VOICE_MODES.items():
        if value == label:
            return key
    return MODE_ROUND_ROBIN


def _safe_int(variable: IntVar, fallback: int) -> int:
    try:
        return int(variable.get())
    except Exception:  # noqa: BLE001 - в поле могли стереть всё
        return fallback


def _safe_float(variable: DoubleVar, fallback: float) -> float:
    try:
        return float(variable.get())
    except Exception:  # noqa: BLE001
        return fallback


def main() -> int:
    setup_logging()
    log.info("Запуск приложения")

    root = Tk()
    try:
        App(root)
    except Exception as exc:
        log.exception("Не удалось построить окно")
        messagebox.showerror(APP_TITLE, f"Не удалось запустить программу:\n{exc}")
        return 1

    root.mainloop()
    log.info("Приложение закрыто")
    return 0
