"""Окно программы: загрузка роликов и управление ботом."""
from __future__ import annotations

import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import config as config_module
from . import logs, registry
from .db import Base
from .guard import Guard
from .tg.app import Runner

log = logs.get_logger("окно")

REFRESH_MS = 1000


class Window(tk.Tk):
    def __init__(self, folder: Path):
        super().__init__()
        self.title("Ролики в телеграм-бота")
        self.geometry("980x680")
        self.minsize(820, 560)

        self.folder = folder
        self.settings = config_module.load(folder)
        self.base = Base(folder / "данные" / "bot.sqlite3")
        self.guard = Guard(self.settings.cpu_limit_percent, self.settings.cpu_grace_s)
        self.runner = Runner(self.base, self.settings, self.guard)

        self.matches: list[registry.Match] = []
        self._lines: queue.Queue[str] = queue.Queue()
        logs.listen(self._lines.put)

        book = ttk.Notebook(self)
        self.upload_tab = ttk.Frame(book)
        self.bot_tab = ttk.Frame(book)
        book.add(self.upload_tab, text="  Загрузка роликов  ")
        book.add(self.bot_tab, text="  Бот  ")
        book.pack(fill="both", expand=True, padx=8, pady=8)

        self._build_upload(self.upload_tab)
        self._build_bot(self.bot_tab)

        for line in logs.recent():
            self._append(line)

        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(REFRESH_MS, self._tick)

        if not config_module.problems(self.settings):
            self.runner.start()

    # --- вкладка загрузки -------------------------------------------------

    def _build_upload(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent)
        top.pack(fill="x", pady=(8, 4))

        ttk.Button(top, text="Выбрать ролики…", command=self._pick).pack(side="left")
        self.send_button = ttk.Button(top, text="Отправить в бота",
                                      command=self._send, state="disabled")
        self.send_button.pack(side="left", padx=6)
        ttk.Button(top, text="Очистить список", command=self._clear).pack(side="left")

        self.pick_note = ttk.Label(top, text="", foreground="#555")
        self.pick_note.pack(side="right")

        columns = ("file", "state", "background", "voice", "music", "duration", "qr")
        self.table = ttk.Treeview(parent, columns=columns, show="headings", height=16)
        for name, title, width in (
            ("file", "Файл", 230),
            # Сюда попадает либо имя ролика из реестра, либо причина отказа, и
            # причина бывает длинной — столбец под неё, а не под имя.
            ("state", "Ролик в реестре", 310),
            ("background", "Фон", 90),
            ("voice", "Озвучка", 90),
            ("music", "Музыка", 70),
            ("duration", "Длина", 70),
            ("qr", "QR", 60),
        ):
            self.table.heading(name, text=title)
            self.table.column(name, width=width, anchor="w")
        self.table.pack(fill="both", expand=True, pady=4)
        self.table.tag_configure("bad", foreground="#a11")

        self.queue_note = ttk.Label(parent, text="")
        self.queue_note.pack(anchor="w", pady=(2, 6))

    def _pick(self) -> None:
        if not self.settings.registry_path:
            messagebox.showwarning(
                "Не указан файл данных",
                "На вкладке «Бот» укажите файл «данные роликов.jsonl» — "
                "он лежит в папке capcut_uniq_data автомонтажа.")
            return

        chosen = filedialog.askopenfilenames(
            title="Ролики", filetypes=[("Видео", "*.mp4 *.mov *.mkv"), ("Все файлы", "*.*")])
        if not chosen:
            return

        known = registry.read(Path(self.settings.registry_path))
        if not known:
            messagebox.showwarning(
                "Реестр пуст",
                "В файле данных нет ни одного ролика. Он заполняется автомонтажом "
                "при сборке — соберите партию и попробуйте снова.")
            return

        self.matches = registry.match_all([Path(item) for item in chosen], known)
        self._redraw()

    def _redraw(self) -> None:
        self.table.delete(*self.table.get_children())
        good = 0
        for item in self.matches:
            if item.ok:
                good += 1
                data = item.data or {}
                self.table.insert("", "end", values=(
                    item.file.name,
                    item.name,
                    {"black": "чёрный", "blur": "размытый"}.get(data.get("background"), "?"),
                    data.get("voice_folder", "?"),
                    "есть" if data.get("music") else "нет",
                    f"{float(data.get('duration_s') or 0):.1f} с",
                    f"{float(data.get('qr_s') or 0):.1f} с",
                ))
            else:
                self.table.insert("", "end", tags=("bad",), values=(
                    item.file.name, item.problem, "", "", "", "", ""))

        bad = len(self.matches) - good
        note = f"Готовы к отправке: {good}"
        if bad:
            note += f", отклонено: {bad}"
        self.pick_note.config(text=note)
        self.send_button.config(state="normal" if good else "disabled")

    def _send(self) -> None:
        added = skipped = 0
        for item in self.matches:
            if not item.ok:
                continue
            if self.base.add_video(item.name, str(item.file), item.data or {}):
                added += 1
            else:
                skipped += 1

        log.info("В очередь поставлено роликов: %d", added)
        self.matches = []
        self._redraw()

        text = f"Поставлено в очередь: {added}."
        if skipped:
            text += f"\nУже были загружены раньше: {skipped}."
        text += "\n\nФайлы должны остаться на месте, пока не зальются."
        messagebox.showinfo("Готово", text)

    def _clear(self) -> None:
        self.matches = []
        self._redraw()

    # --- вкладка бота -----------------------------------------------------

    def _build_bot(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text=" Настройки ")
        box.pack(fill="x", pady=8, padx=2)
        box.columnconfigure(1, weight=1)

        self.token = tk.StringVar(value=self.settings.token)
        self.admin_id = tk.StringVar(value=str(self.settings.admin_id or ""))
        self.registry_path = tk.StringVar(value=self.settings.registry_path)

        ttk.Label(box, text="Токен бота").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        entry = ttk.Entry(box, textvariable=self.token, show="•")
        entry.grid(row=0, column=1, sticky="ew", padx=6)
        self.show_token = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="показать", variable=self.show_token,
                        command=lambda: entry.config(show="" if self.show_token.get() else "•")
                        ).grid(row=0, column=2, padx=6)

        ttk.Label(box, text="Ваш ID").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(box, textvariable=self.admin_id, width=20).grid(row=1, column=1, sticky="w", padx=6)
        ttk.Label(box, text="можно оставить пустым: админом станет тот, кто первым нажмёт «Старт»",
                  foreground="#555").grid(row=1, column=2, sticky="w", padx=6)

        ttk.Label(box, text="Данные автомонтажа").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(box, textvariable=self.registry_path).grid(row=2, column=1, sticky="ew", padx=6)
        ttk.Button(box, text="Выбрать…", command=self._pick_registry).grid(row=2, column=2, padx=6)

        buttons = ttk.Frame(parent)
        buttons.pack(fill="x", pady=6)
        ttk.Button(buttons, text="Сохранить", command=self._save).pack(side="left")
        self.power = ttk.Button(buttons, text="Запустить бота", command=self._toggle)
        self.power.pack(side="left", padx=6)
        self.state_note = ttk.Label(buttons, text="")
        self.state_note.pack(side="left", padx=10)

        self.journal = tk.Text(parent, height=18, wrap="word", state="disabled",
                               background="#111", foreground="#ddd", insertbackground="#ddd")
        self.journal.pack(fill="both", expand=True, pady=(6, 4))

    def _pick_registry(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Файл данных автомонтажа",
            filetypes=[("Реестр роликов", "*.jsonl"), ("Все файлы", "*.*")])
        if chosen:
            self.registry_path.set(chosen)

    def _save(self) -> None:
        self.settings.token = self.token.get().strip()
        self.settings.registry_path = self.registry_path.get().strip()
        raw = self.admin_id.get().strip()
        self.settings.admin_id = int(raw) if raw.isdigit() else 0

        config_module.save(self.folder, self.settings)

        troubles = config_module.problems(self.settings)
        if troubles:
            messagebox.showwarning("Сохранено, но бота не запустить",
                                   "\n".join("• " + item for item in troubles))
            return
        messagebox.showinfo("Сохранено", "Настройки записаны.")

    def _toggle(self) -> None:
        if self.runner.running:
            self.runner.stop()
            return

        self._save_quietly()
        troubles = config_module.problems(self.settings)
        if troubles:
            messagebox.showwarning("Бота не запустить",
                                   "\n".join("• " + item for item in troubles))
            return
        self.runner.start()

    def _save_quietly(self) -> None:
        self.settings.token = self.token.get().strip()
        self.settings.registry_path = self.registry_path.get().strip()
        raw = self.admin_id.get().strip()
        self.settings.admin_id = int(raw) if raw.isdigit() else 0
        config_module.save(self.folder, self.settings)

    # --- общее ------------------------------------------------------------

    def _append(self, line: str) -> None:
        self.journal.config(state="normal")
        self.journal.insert("end", line + "\n")
        self.journal.see("end")
        # Держим в окне только хвост: за сутки работы текста набегает столько,
        # что окно начинает заметно тормозить при прокрутке.
        if int(self.journal.index("end-1c").split(".")[0]) > 600:
            self.journal.delete("1.0", "200.0")
        self.journal.config(state="disabled")

    def _tick(self) -> None:
        while True:
            try:
                self._append(self._lines.get_nowait())
            except queue.Empty:
                break

        counts = self.base.counts()
        note = (f"В очереди на заливку: {counts['pending']}   "
                f"свободных роликов: {counts['free']}   всего залито: {counts['ready']}")
        if counts["failed"]:
            note += f"   не залилось: {counts['failed']}"
        self.queue_note.config(text=note)

        if self.runner.running:
            self.power.config(text="Остановить бота")
            state = "работает"
            if self.guard.paused:
                state = f"на паузе, процессор {self.guard.last_percent:.0f}%"
            self.state_note.config(text=state)
        else:
            self.power.config(text="Запустить бота")
            self.state_note.config(
                text=f"остановлен — {self.runner.error}" if self.runner.error else "остановлен")

        self.after(REFRESH_MS, self._tick)

    def _close(self) -> None:
        self.runner.stop(timeout=5.0)
        self.destroy()


def run(folder: Path) -> None:
    Window(folder).mainloop()
