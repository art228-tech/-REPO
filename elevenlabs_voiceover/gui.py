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
    Listbox,
    StringVar,
    Tk,
    Variable,
    X,
    Y,
    filedialog,
    messagebox,
    scrolledtext,
    ttk,
)
from typing import Any, List, Optional

from . import clipboard, diagnostics
from .api_client import (
    PROXY_SCHEME_CANDIDATES,
    ElevenLabsClient,
    ModelInfo,
    decoder_support,
    describe_route,
    detect_proxy_scheme,
    hide_credentials,
    outbound_address,
    probe_connection,
    swap_proxy_scheme,
    verify_key,
)
from .audio import extension_for, find_ffmpeg
from .config import (
    DEFAULT_GUIDANCE,
    DONE_ACTIONS,
    DONE_DELETE,
    DONE_FOLDER_NAME,
    DONE_KEEP,
    DONE_MOVE,
    MODE_ALL_VOICES,
    MODE_ROUND_ROBIN,
    SOURCE_ACCOUNT,
    SOURCE_DESIGN,
    VOICE_MODES,
    VOICE_SOURCES,
    Settings,
    normalize_proxy_url,
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
        self.account_voices: List[Any] = []
        self.folder_rows: dict = {}

        self._save_job: Optional[str] = None
        self._autosave_ready = False

        self._build_ui()
        self._settings_to_widgets()
        self._enable_autosave()

        self.log_handler = add_gui_handler(self._enqueue_log)
        self.root.after(100, self._drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        register_secret(self.settings.api_key)
        self._refresh_estimate()
        self._report_ffmpeg()
        self._refresh_proxy_hint()
        self._on_save_beside_changed()
        self._on_voice_source_changed()
        self._refresh_done_hint()

    # ==================================================================
    # Построение интерфейса
    # ==================================================================
    def _build_ui(self) -> None:
        self.root.title(APP_TITLE)
        self.root.geometry("1000x820")
        self.root.minsize(860, 600)

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

        self.tab_work = ttk.Frame(self.notebook)
        self.tab_settings = ttk.Frame(self.notebook)
        self.tab_log = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.tab_work, text="  Работа  ")
        self.notebook.add(self.tab_settings, text="  Настройки  ")
        self.notebook.add(self.tab_log, text="  Журнал  ")

        # Обе вкладки прокручиваемые: настроек много, и на ноутбучном экране
        # нижние строки иначе уезжают за край.
        self._build_work_tab(_scrollable(self.tab_work))
        self._build_settings_tab(_scrollable(self.tab_settings))
        self._build_log_tab(self.tab_log)
        self._enable_clipboard()

    def _enable_autosave(self) -> None:
        """Сохранять настройки сразу, а не только при запуске и выходе.

        Поля перебираем по атрибутам var_*, а не списком: список рано или
        поздно разойдётся с окном, и очередная настройка потеряется.
        """
        for name, value in vars(self).items():
            if name.startswith("var_") and isinstance(value, Variable):
                value.trace_add("write", lambda *_: self._schedule_save())

        self.txt_preview.bind("<KeyRelease>", lambda _e: self._schedule_save())
        self.txt_preview.bind("<<Paste>>", lambda _e: self._schedule_save())
        self._autosave_ready = True

    def _schedule_save(self) -> None:
        """Отложить запись: пока человек печатает, писать на диск каждый символ ни к чему."""
        if not self._autosave_ready:
            return
        if self._save_job is not None:
            try:
                self.root.after_cancel(self._save_job)
            except Exception:  # noqa: BLE001
                pass
        self._save_job = self.root.after(700, self._save_now)

    def _save_now(self) -> None:
        self._save_job = None
        try:
            self._widgets_to_settings().save()
        except Exception as exc:  # noqa: BLE001 - неудачная запись не должна мешать работе
            log.debug("Не удалось сохранить настройки: %s", exc)

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
                               "Папка с .txt, в каждом — описание одного голоса", key="prompts")
        row = self._folder_row(parent, row, "Тексты для озвучки:", self.var_texts_dir,
                               "Папка с .txt, каждый файл станет отдельной озвучкой")
        self.var_save_beside = BooleanVar(value=False)
        ttk.Checkbutton(
            parent,
            text="Складывать результат рядом с текстом, под тем же именем",
            variable=self.var_save_beside,
            command=self._on_save_beside_changed,
        ).grid(row=row, column=1, columnspan=2, sticky="w", pady=(2, 0))
        row += 1

        self.lbl_beside = ttk.Label(parent, text="", style="Hint.TLabel",
                                    justify=LEFT, wraplength=620)
        self.lbl_beside.grid(row=row, column=1, columnspan=2, sticky="w", pady=(0, 6))
        row += 1

        row = self._folder_row(parent, row, "Куда сохранять:", self.var_output_dir,
                               "Готовые файлы, превью голосов и список _manifest.csv",
                               key="output")

        ttk.Separator(parent, orient="horizontal").grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)
        row += 1

        ttk.Label(parent, text="Порядок работы", style="Head.TLabel").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )
        row += 1

        ttk.Label(parent, text="Откуда голоса:").grid(row=row, column=0, sticky="w", pady=3)
        self.var_voice_source = StringVar(value=VOICE_SOURCES[SOURCE_DESIGN])
        combo_source = ttk.Combobox(
            parent, textvariable=self.var_voice_source, state="readonly",
            values=[VOICE_SOURCES[SOURCE_DESIGN], VOICE_SOURCES[SOURCE_ACCOUNT]],
        )
        combo_source.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        combo_source.bind("<<ComboboxSelected>>", lambda _e: self._on_voice_source_changed())
        row += 1

        self.frame_account_voices = ttk.Frame(parent)
        self.frame_account_voices.grid(row=row, column=1, columnspan=2, sticky="ew", pady=(0, 6))
        self.frame_account_voices.columnconfigure(0, weight=1)

        ttk.Label(
            self.frame_account_voices,
            text="Отметьте голоса из личного кабинета. Создать их можно на сайте: "
                 "Voices — My Voices — Add a new voice — Voice Design.",
            style="Hint.TLabel", justify=LEFT, wraplength=620,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))

        self.list_voices = Listbox(self.frame_account_voices, selectmode="extended", height=5,
                                   exportselection=False)
        self.list_voices.grid(row=1, column=0, sticky="ew")
        self.list_voices.bind("<<ListboxSelect>>", lambda _e: self._on_voice_selection())

        buttons = ttk.Frame(self.frame_account_voices)
        buttons.grid(row=1, column=1, sticky="nw", padx=(8, 0))
        ttk.Button(buttons, text="Обновить", width=11, command=self._load_account_voices).pack()
        ttk.Button(buttons, text="Все свои", width=11, command=self._select_own_voices).pack(pady=(4, 0))

        self.lbl_voices_hint = ttk.Label(self.frame_account_voices, text="Список ещё не загружен",
                                         style="Hint.TLabel")
        self.lbl_voices_hint.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 1

        self.lbl_max_voices = ttk.Label(parent, text="Голосов создать:")
        self.lbl_max_voices.grid(row=row, column=0, sticky="w", pady=3)
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

        self.lbl_voice_mode = ttk.Label(parent, text="", style="Hint.TLabel",
                                        justify=LEFT, wraplength=620)
        self.lbl_voice_mode.grid(row=row, column=1, columnspan=2, sticky="w", pady=(0, 4))
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
        self, parent: ttk.Frame, row: int, label: str, variable: StringVar, hint: str,
        key: str = "",
    ) -> int:
        caption = ttk.Label(parent, text=label)
        caption.grid(row=row, column=0, sticky="w", pady=3)

        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        variable.trace_add("write", lambda *_: self._refresh_estimate())

        buttons = ttk.Frame(parent)
        buttons.grid(row=row, column=2, sticky="w", padx=(8, 0))
        ttk.Button(buttons, text="Обзор…", width=9,
                   command=lambda v=variable: self._pick_folder(v)).pack(side=LEFT)
        ttk.Button(buttons, text="Открыть", width=9,
                   command=lambda v=variable: self._open_path(v.get())).pack(side=LEFT, padx=(4, 0))

        note = ttk.Label(parent, text=hint, style="Hint.TLabel")
        note.grid(row=row + 1, column=1, columnspan=2, sticky="w", pady=(0, 6))

        if key:
            self.folder_rows[key] = (caption, entry, buttons, note)
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

        row = self._separator(canvas_frame, row, "Файлы на выходе")

        ttk.Label(canvas_frame, text="Текст после озвучки:").grid(row=row, column=0, sticky="w", pady=3)
        self.var_done_action = StringVar(value=DONE_ACTIONS[DONE_KEEP])
        combo_done = ttk.Combobox(
            canvas_frame, textvariable=self.var_done_action, state="readonly",
            values=[DONE_ACTIONS[DONE_KEEP], DONE_ACTIONS[DONE_MOVE], DONE_ACTIONS[DONE_DELETE]],
        )
        combo_done.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        combo_done.bind("<<ComboboxSelected>>", lambda _e: self._refresh_done_hint())
        row += 1

        self.lbl_done_action = ttk.Label(canvas_frame, text="", style="Hint.TLabel",
                                         justify=LEFT, wraplength=700)
        self.lbl_done_action.grid(row=row, column=1, columnspan=2, sticky="w", pady=(0, 6))
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
        row += 1

        row = self._separator(canvas_frame, row, "Сеть")

        ttk.Label(canvas_frame, text="Прокси:").grid(row=row, column=0, sticky="w", pady=3)
        self.var_proxy = StringVar(value="")
        ttk.Entry(canvas_frame, textvariable=self.var_proxy).grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=3
        )
        row += 1
        ttk.Label(
            canvas_frame,
            text="Пусто — как настроено в Windows. Понимает socks5h://127.0.0.1:1080, "
                 "http://127.0.0.1:8080 и запись продавцов прокси адрес:порт:логин:пароль.",
            style="Hint.TLabel", justify=LEFT, wraplength=700,
        ).grid(row=row, column=1, columnspan=2, sticky="w")
        row += 1

        self.lbl_proxy = ttk.Label(canvas_frame, text="", style="Hint.TLabel",
                                   justify=LEFT, wraplength=700)
        self.lbl_proxy.grid(row=row, column=1, columnspan=2, sticky="w", pady=(0, 6))
        self.var_proxy.trace_add("write", lambda *_: self._refresh_proxy_hint())
        row += 1

        self.var_ignore_system_proxy = BooleanVar(value=False)
        ttk.Checkbutton(canvas_frame, text="Не использовать системный прокси Windows",
                        variable=self.var_ignore_system_proxy).grid(
            row=row, column=1, columnspan=2, sticky="w", pady=3
        )

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
        ttk.Button(extras, text="Проверить соединение", command=self._probe_connection).pack(side=LEFT)
        ttk.Button(extras, text="Собрать отчёт о проблеме", command=self._build_report).pack(
            side=LEFT, padx=(8, 0)
        )
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
        self.var_voice_source.set(VOICE_SOURCES.get(s.voice_source, VOICE_SOURCES[SOURCE_DESIGN]))
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
        self.var_done_action.set(DONE_ACTIONS.get(s.done_action, DONE_ACTIONS[DONE_KEEP]))
        self.var_save_beside.set(s.save_next_to_texts)
        self.var_keep_chunks.set(s.keep_chunks)
        self.var_use_ffmpeg.set(s.use_ffmpeg)
        self.var_proxy.set(s.proxy_url)
        self.var_ignore_system_proxy.set(s.ignore_system_proxy)

    def _widgets_to_settings(self) -> Settings:
        s = self.settings
        s.api_key = self.var_api_key.get().strip()
        s.remember_api_key = bool(self.var_remember_key.get())
        s.prompts_dir = self.var_prompts_dir.get().strip()
        s.texts_dir = self.var_texts_dir.get().strip()
        s.output_dir = self.var_output_dir.get().strip()
        s.max_voices = _safe_int(self.var_max_voices, s.max_voices)
        s.voice_mode = _mode_from_label(self.var_voice_mode.get())
        s.voice_source = _source_from_label(self.var_voice_source.get())
        if self.account_voices:
            # Пока список не загружен, прежний выбор затирать нельзя.
            s.selected_voice_ids = self._selected_voice_ids()
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
        s.done_action = _done_from_label(self.var_done_action.get())
        s.save_next_to_texts = bool(self.var_save_beside.get())
        s.keep_chunks = bool(self.var_keep_chunks.get())
        s.use_ffmpeg = bool(self.var_use_ffmpeg.get())
        s.proxy_url = self.var_proxy.get().strip()
        s.ignore_system_proxy = bool(self.var_ignore_system_proxy.get())

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

    def _refresh_done_hint(self) -> None:
        action = _done_from_label(self.var_done_action.get())

        if action == DONE_DELETE:
            self.lbl_done_action.configure(
                text="Исходный txt будет удалён сразу после того, как готовая озвучка окажется "
                     "на диске. Восстановить его будет неоткуда — корзина не используется.",
                style="Bad.TLabel",
            )
        elif action == DONE_MOVE:
            self.lbl_done_action.configure(
                text=f"Озвученные тексты переедут в подпапку «{DONE_FOLDER_NAME}» рядом с ними. "
                     "Повторный запуск их больше не увидит, но файлы останутся при вас.",
                style="Hint.TLabel",
            )
        else:
            self.lbl_done_action.configure(
                text="Тексты остаются на месте. Повторный запуск пропустит уже озвученные.",
                style="Hint.TLabel",
            )
        self._schedule_save()

    def _on_save_beside_changed(self) -> None:
        """Показать или спрятать выбор папки результатов."""
        beside = bool(self.var_save_beside.get())

        for widget in self.folder_rows.get("output", ()):
            if beside:
                widget.grid_remove()
            else:
                widget.grid()

        if beside:
            example = "текст1.txt рядом появится текст1" + extension_for(self.var_output_format.get())
            self.lbl_beside.configure(
                text=f"Готовые файлы лягут в папку с текстами: с {example}. "
                     "Туда же попадут превью голосов и список _manifest.csv."
            )
        else:
            self.lbl_beside.configure(text="")

        self._schedule_save()

    def _on_voice_source_changed(self) -> None:
        """Показать или спрятать список голосов аккаунта."""
        from_account = _source_from_label(self.var_voice_source.get()) == SOURCE_ACCOUNT

        if from_account:
            self.frame_account_voices.grid()
            self.lbl_max_voices.configure(text="Голосов брать:")
            # Промпты в этом режиме не нужны: голоса уже созданы на сайте.
            for widget in self.folder_rows.get("prompts", ()):
                widget.grid_remove()
            if not self.account_voices:
                self._load_account_voices()
        else:
            self.frame_account_voices.grid_remove()
            self.lbl_max_voices.configure(text="Голосов создать:")
            for widget in self.folder_rows.get("prompts", ()):
                widget.grid()

        self._refresh_estimate()

    def _load_account_voices(self) -> None:
        settings = self._widgets_to_settings()
        if not settings.resolved_api_key():
            self.lbl_voices_hint.configure(text="Сначала укажите API-ключ", style="Bad.TLabel")
            return

        self.lbl_voices_hint.configure(text="Загружаю список голосов…", style="Hint.TLabel")

        def work() -> None:
            client = None
            try:
                client = ElevenLabsClient(
                    settings.resolved_api_key(),
                    timeout=settings.request_timeout,
                    max_retries=2,
                    proxy_url=settings.proxy_url,
                    ignore_system_proxy=settings.ignore_system_proxy,
                )
                voices = client.account_voices()
            except Exception as exc:  # noqa: BLE001
                self.events.put(("voices_failed", str(exc)))
            else:
                self.events.put(("voices_loaded", voices))
            finally:
                if client:
                    client.close()

        threading.Thread(target=work, daemon=True).start()

    def _on_voices_loaded(self, voices: List[Any]) -> None:
        self.account_voices = voices
        self.list_voices.delete(0, END)
        for voice in voices:
            self.list_voices.insert(END, voice.label())

        # Восстанавливаем прежний выбор: список мог обновиться, но отмеченное
        # человеком терять нельзя.
        chosen = set(self.settings.selected_voice_ids)
        for index, voice in enumerate(voices):
            if voice.voice_id in chosen:
                self.list_voices.selection_set(index)

        own = sum(1 for v in voices if v.is_custom)
        self.lbl_voices_hint.configure(
            text=f"Найдено голосов: {len(voices)}, из них своих: {own}", style="Hint.TLabel"
        )
        self._refresh_estimate()

    def _select_own_voices(self) -> None:
        self.list_voices.selection_clear(0, END)
        for index, voice in enumerate(self.account_voices):
            if voice.is_custom:
                self.list_voices.selection_set(index)
        self._on_voice_selection()

    def _on_voice_selection(self) -> None:
        self._schedule_save()
        self._refresh_estimate()

    def _selected_voice_ids(self) -> List[str]:
        return [
            self.account_voices[i].voice_id
            for i in self.list_voices.curselection()
            if i < len(self.account_voices)
        ]

    def _refresh_proxy_hint(self) -> None:
        """Показать, во что превратился введённый адрес.

        Непонятный адрес программа отбрасывает; без подписи это выглядит как
        будто настройка просто не работает.
        """
        raw = self.var_proxy.get().strip()
        if not raw:
            self.lbl_proxy.configure(text="Сейчас: путь в сеть берётся из настроек Windows.",
                                     style="Hint.TLabel")
            return

        parsed = normalize_proxy_url(raw)
        if parsed:
            self.lbl_proxy.configure(
                text=f"Будет использован: {hide_credentials(parsed)}"
                     + (" (с логином и паролем)" if "@" in parsed else ""),
                style="Good.TLabel",
            )
        else:
            self.lbl_proxy.configure(
                text="Адрес не разобран, прокси использован не будет. "
                     "Ожидается вид адрес:порт, адрес:порт:логин:пароль либо со схемой впереди.",
                style="Bad.TLabel",
            )

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

        route = describe_route(settings.proxy_url, settings.ignore_system_proxy)
        log.info("Проверяю ключ, путь в сеть: %s", route)

        def work() -> None:
            try:
                subscription, models = verify_key(
                    key,
                    timeout=settings.request_timeout,
                    proxy_url=settings.proxy_url,
                    ignore_system_proxy=settings.ignore_system_proxy,
                )
            except ElevenLabsError as exc:
                self.events.put(("verify_failed", f"{exc}\n\nЗапрос шёл {route}."))
            except Exception as exc:  # noqa: BLE001
                self.events.put(("verify_failed", f"Непредвиденная ошибка: {exc}\n\nЗапрос шёл {route}."))
            else:
                self.events.put(("verify_ok", subscription, models))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------
    def _refresh_estimate(self) -> None:
        try:
            settings = self._widgets_to_settings()
        except Exception:  # noqa: BLE001 - виджеты могли ещё не создаться
            return

        needs_prompts = settings.voice_source == SOURCE_DESIGN
        if not settings.texts_dir or (needs_prompts and not settings.prompts_dir):
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

        if needs_prompts:
            head = f"Найдено: промптов {plan['prompts']} (будет создано голосов {plan['voices']})"
            tail = f", из них {_fmt(plan['design_credits'])} на создание голосов."
        else:
            head = f"Голосов выбрано: {plan['voices']}"
            tail = ". Голоса уже созданы, кредиты на них не тратятся."

        self.lbl_estimate.configure(
            text=(
                f"{head}, текстов {plan['texts']}, "
                f"файлов на выходе {_fmt(plan['outputs'])}, "
                f"символов {_fmt(plan['characters'])}.\n"
                f"Ориентировочный расход: около {_fmt(credits)} кредитов{tail}"
            )
        )
        self._refresh_voice_mode_hint(plan)

    def _refresh_voice_mode_hint(self, plan: dict) -> None:
        """Показать, сколько файлов даст выбранный режим раздачи голосов.

        Названия режимов путают: «всеми голосами» легко прочесть как «задействуй
        мои голоса», а не «сделай по файлу на каждый». Цифры снимают вопрос.
        """
        texts = int(plan.get("texts") or 0)
        voices = max(1, int(plan.get("voices") or 1))

        if _mode_from_label(self.var_voice_mode.get()) == MODE_ALL_VOICES:
            self.lbl_voice_mode.configure(
                text=f"Каждый текст будет озвучен всеми голосами: {texts} текстов дадут "
                     f"{_fmt(texts * voices)} файлов, и расход кредитов вырастет во столько же раз.",
                style="Bad.TLabel" if voices > 1 else "Hint.TLabel",
            )
        else:
            self.lbl_voice_mode.configure(
                text=f"Один текст — один файл: {texts} текстов дадут {_fmt(texts)} файлов. "
                     "Голоса чередуются по очереди.",
                style="Hint.TLabel",
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

        if settings.done_action == DONE_DELETE and not messagebox.askyesno(
            APP_TITLE,
            "Включено удаление исходных текстов.\n\n"
            "Каждый txt будет удалён сразу после того, как его озвучка окажется на диске. "
            "Корзина не используется, вернуть файлы будет неоткуда.\n\n"
            "Продолжить?",
            icon="warning",
            default="no",
            parent=self.root,
        ):
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

    def _probe_connection(self) -> None:
        """Постучаться в API напрямую и показать, что вернулось."""
        settings = self._widgets_to_settings()
        self.lbl_status.configure(text="Проверяю соединение…")
        self._set_busy(True)

        def work() -> None:
            try:
                results = probe_connection(
                    settings.resolved_api_key(),
                    timeout=settings.request_timeout,
                    proxy_url=settings.proxy_url,
                    ignore_system_proxy=settings.ignore_system_proxy,
                )
            except Exception as exc:
                log.exception("Проверка соединения упала")
                self.events.put(("probe_failed", str(exc)))
            else:
                self.events.put(("probe_done", results))

        threading.Thread(target=work, daemon=True).start()

    def _on_probe_done(self, results: List[Any]) -> None:
        self._set_busy(False)
        self.lbl_status.configure(text="Проверка соединения завершена")

        broken = [r for r in results if r.error or not r.json_ok]

        # Прокси не отозвался — почти всегда дело в схеме: адрес продают без
        # неё, а http и socks5 на вид неотличимы. Подберём сами.
        if broken and self.settings.proxy_url and any("прокси" in (r.error or "") for r in broken):
            self._offer_working_proxy_scheme()
            return
        report = "\n\n".join(r.line() for r in results)
        settings = self.settings
        outbound = outbound_address(
            proxy_url=settings.proxy_url, ignore_system_proxy=settings.ignore_system_proxy
        )
        tail = (
            f"\n\nПуть в сеть: {describe_route(settings.proxy_url, settings.ignore_system_proxy)}"
            f"\nВыход в интернет: {outbound or 'определить не удалось'}"
            f"\nСжатие, доступное программе: {decoder_support()}"
        )

        if not broken:
            messagebox.showinfo(
                APP_TITLE,
                "Соединение в порядке, API отвечает как положено.\n\n" + report + tail,
                parent=self.root,
            )
            return

        messagebox.showwarning(
            APP_TITLE,
            "Часть запросов вернулась не такой, как ожидалось.\n\n"
            + report
            + tail
            + "\n\nПодробности записаны в журнал. Нажмите «Собрать отчёт о проблеме», "
              "чтобы отправить их на разбор.",
            parent=self.root,
        )

    def _offer_working_proxy_scheme(self) -> None:
        """Перебрать схемы прокси и предложить ту, что отвечает."""
        current = self.settings.proxy_url
        self.lbl_status.configure(text="Прокси не ответил, подбираю схему…")
        self._set_busy(True)

        def work() -> None:
            scheme = detect_proxy_scheme(current)
            self.events.put(("proxy_scheme", scheme, current))

        threading.Thread(target=work, daemon=True).start()

    def _on_proxy_scheme(self, scheme: Optional[str], previous: str) -> None:
        self._set_busy(False)

        if not scheme:
            self.lbl_status.configure(text="Прокси не отвечает")
            messagebox.showwarning(
                APP_TITLE,
                f"Прокси {hide_credentials(previous)} не отвечает ни по одной из схем "
                f"({', '.join(PROXY_SCHEME_CANDIDATES)}).\n\n"
                "Проверьте адрес, порт, логин и пароль. Если прокси платный — не истёк ли срок. "
                "Либо очистите поле «Прокси», чтобы выходить в сеть напрямую.",
                parent=self.root,
            )
            return

        working = swap_proxy_scheme(previous, scheme)
        self.lbl_status.configure(text=f"Прокси отвечает по схеме {scheme}")

        if messagebox.askyesno(
            APP_TITLE,
            f"Прокси не отвечает по текущей схеме, но отзывается по «{scheme}».\n\n"
            f"Записать как {hide_credentials(working)} и проверить снова?",
            parent=self.root,
        ):
            self.var_proxy.set(working)
            self._save_now()
            self._probe_connection()

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
        elif kind == "probe_done":
            self._on_probe_done(event[1])
        elif kind == "voices_loaded":
            self._on_voices_loaded(event[1])
        elif kind == "voices_failed":
            self.lbl_voices_hint.configure(
                text=f"Список голосов получить не удалось: {event[1][:120]}", style="Bad.TLabel"
            )
        elif kind == "proxy_scheme":
            self._on_proxy_scheme(event[1], event[2])
        elif kind == "probe_failed":
            self._set_busy(False)
            self.lbl_status.configure(text="Проверка соединения не удалась")
            messagebox.showerror(APP_TITLE, event[1], parent=self.root)
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
    if settings.voice_source == SOURCE_DESIGN and (
        not settings.prompts_dir or not Path(settings.prompts_dir).is_dir()
    ):
        problems.append("не выбрана папка с промптами голосов")
    if settings.voice_source == SOURCE_ACCOUNT and not settings.selected_voice_ids:
        problems.append("не отмечен ни один голос из личного кабинета")
    if not settings.texts_dir or not Path(settings.texts_dir).is_dir():
        problems.append("не выбрана папка с текстами")
    if not settings.save_next_to_texts and not settings.output_dir:
        problems.append("не выбрана папка для результатов")
    return problems


def _mode_from_label(label: str) -> str:
    for key, value in VOICE_MODES.items():
        if value == label:
            return key
    return MODE_ROUND_ROBIN


def _done_from_label(label: str) -> str:
    for key, value in DONE_ACTIONS.items():
        if value == label:
            return key
    return DONE_KEEP


def _source_from_label(label: str) -> str:
    for key, value in VOICE_SOURCES.items():
        if value == label:
            return key
    return SOURCE_DESIGN


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
