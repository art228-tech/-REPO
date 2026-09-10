"""Окно программы: загрузка роликов, бот и журнал."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import config as config_module
from . import logs, registry, report
from .db import Base
from .guard import Guard
from .tg.app import Runner

log = logs.get_logger("окно")

REFRESH_MS = 1000


class Window(tk.Tk):
    def __init__(self, folder: Path):
        super().__init__()
        self.title("Ролики в телеграм-бота")
        self.geometry("1000x720")
        self.minsize(860, 600)

        self.folder = folder
        self.settings = config_module.load(folder)
        self.base = Base(folder / "данные" / "bot.sqlite3")
        self.guard = Guard(self.settings.cpu_limit_percent, self.settings.cpu_grace_s)
        self.runner = Runner(self.base, self.settings, self.guard)

        self.matches: list[registry.Match] = []
        self._lines: queue.Queue[tuple[str, bool]] = queue.Queue()
        logs.listen(self._catch)

        book = ttk.Notebook(self)
        self.upload_tab = ttk.Frame(book)
        self.bot_tab = ttk.Frame(book)
        self.journal_tab = ttk.Frame(book)
        book.add(self.upload_tab, text="  Загрузка роликов  ")
        book.add(self.bot_tab, text="  Бот  ")
        book.add(self.journal_tab, text="  Журнал  ")
        book.pack(fill="both", expand=True, padx=8, pady=8)

        self._build_upload(self.upload_tab)
        self._build_bot(self.bot_tab)
        self._build_journal(self.journal_tab)

        for line in logs.recent():
            self._append(line, line in set(logs.errors()))

        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(REFRESH_MS, self._tick)
        self._to_front()

        log.info("Программа открыта")
        if not config_module.problems(self.settings):
            self.runner.start()

    def _to_front(self) -> None:
        """Показывает окно поверх остальных.

        Иначе окно открывается за чужими — например за CapCut на весь экран, —
        и выглядит это как «программа не запустилась».
        """
        try:
            self.lift()
            self.attributes("-topmost", True)
            self.after(600, lambda: self.attributes("-topmost", False))
            self.focus_force()
        except tk.TclError:
            pass

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

        self.trouble = ttk.Label(parent, text="", foreground="#a11", wraplength=900,
                                 justify="left")
        self.trouble.pack(anchor="w", pady=(8, 0), padx=2)

    def _pick_registry(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Файл данных автомонтажа",
            filetypes=[("Реестр роликов", "*.jsonl"), ("Все файлы", "*.*")])
        if chosen:
            self.registry_path.set(chosen)

    def _save(self) -> None:
        self._save_quietly()
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

    # --- вкладка журнала --------------------------------------------------

    def _build_journal(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent)
        top.pack(fill="x", pady=(8, 4))

        self.only_errors = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Только ошибки", variable=self.only_errors,
                        command=self._refill).pack(side="left")
        ttk.Button(top, text="Собрать отчёт о проблеме",
                   command=self._report).pack(side="left", padx=(12, 6))
        ttk.Button(top, text="Открыть папку журналов",
                   command=self._open_journals).pack(side="left")

        ttk.Label(
            parent,
            text="Отчёт — один файл, который можно переслать. "
                 "Внутри журналы, окружение и настройки; токен из него вырезан.",
            foreground="#555").pack(anchor="w", pady=(0, 4))

        self.journal = tk.Text(parent, height=22, wrap="word", state="disabled",
                               background="#111", foreground="#ddd",
                               insertbackground="#ddd")
        self.journal.pack(fill="both", expand=True, pady=(4, 4))
        self.journal.tag_configure("bad", foreground="#ff8a80")

    def _report(self) -> None:
        try:
            where = report.build(self.folder, self.settings, self.base)
        except Exception as exc:  # noqa: BLE001 - отчёт о сбое не должен падать сам
            log.error("Отчёт собрать не вышло: %s", exc)
            messagebox.showerror("Не вышло", f"Отчёт собрать не удалось:\n{exc}")
            return

        log.info("Отчёт собран: %s", where.name)
        messagebox.showinfo(
            "Отчёт готов",
            f"{where}\n\nТокен из отчёта вырезан — файл можно пересылать.")
        self._reveal(where.parent)

    def _open_journals(self) -> None:
        self._reveal(self.folder / "данные" / "журналы")

    def _reveal(self, where: Path) -> None:
        """Открывает папку в проводнике — на каждой системе по-своему."""
        try:
            where.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(where)  # noqa: S606 - открыть папку пользователю
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(where)])
            else:
                subprocess.Popen(["xdg-open", str(where)])
        except Exception as exc:  # noqa: BLE001 - не открылось, и ладно
            log.warning("Папку открыть не вышло: %s", exc)
            messagebox.showinfo("Папка", str(where))

    def _refill(self) -> None:
        self.journal.config(state="normal")
        self.journal.delete("1.0", "end")
        self.journal.config(state="disabled")

        errors = set(logs.errors())
        source = logs.errors() if self.only_errors.get() else logs.recent()
        for line in source:
            self._append(line, line in errors)

    # --- общее ------------------------------------------------------------

    def _catch(self, line: str) -> None:
        """Принимает строку журнала из чужого потока — бот пишет из своего."""
        self._lines.put((line, False))

    def _append(self, line: str, bad: bool) -> None:
        self.journal.config(state="normal")
        self.journal.insert("end", line + "\n", ("bad",) if bad else ())
        self.journal.see("end")
        # Держим в окне только хвост: за сутки работы текста набегает столько,
        # что окно начинает заметно тормозить при прокрутке.
        if int(self.journal.index("end-1c").split(".")[0]) > 600:
            self.journal.delete("1.0", "200.0")
        self.journal.config(state="disabled")

    def _tick(self) -> None:
        errors = set(logs.errors())
        while True:
            try:
                line, _ = self._lines.get_nowait()
            except queue.Empty:
                break
            if self.only_errors.get() and line not in errors:
                continue
            self._append(line, line in errors)

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
            self.trouble.config(text="")
        else:
            self.power.config(text="Запустить бота")
            self.state_note.config(text="остановлен")
            self.trouble.config(text=self.runner.error)

        self.after(REFRESH_MS, self._tick)

    def _close(self) -> None:
        self.runner.stop(timeout=5.0)
        self.destroy()


def run(folder: Path) -> None:
    """Открывает окно. Сбой при построении окна обязан дойти до человека."""
    try:
        window = Window(folder)
    except Exception as error:  # noqa: BLE001 - причина уходит в файл и наверх
        logs.get_logger("окно").error(
            "Окно не построилось: %s\n%s", error,
            "".join(traceback.format_exception(type(error), error, error.__traceback__)))
        raise
    window.mainloop()
