"""Окно программы.

Сделано на tkinter, который входит в состав Python, — чтобы на Windows ничего
не пришлось доустанавливать. Сборка идёт в отдельном потоке, журнал течёт в
окно в реальном времени.
"""
from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import batch, logging_setup
from .config import Config, _default_drafts_dir
from .errors import PipelineError

PAD = 8


class QueueHandler(logging.Handler):
    """Перекладывает записи журнала в очередь, откуда их забирает окно."""

    def __init__(self, sink: queue.Queue):
        super().__init__()
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self.sink.put((record.levelno, self.format(record)))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Сборка роликов CapCut по шаблонам")
        self.geometry("980x720")
        self.minsize(820, 600)

        self.messages: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.log_path: Path | None = None

        self.clips_dir = tk.StringVar()
        self.voice_dir = tk.StringVar()
        self.drafts_dir = tk.StringVar(value=str(_default_drafts_dir()))
        self.count = tk.IntVar(value=10)
        self.seed = tk.StringVar()
        self.fps = tk.StringVar(value="60")
        self.prefix = tk.StringVar(value="auto")
        self.make_subtitles = tk.BooleanVar(value=True)
        self.consume = tk.BooleanVar(value=True)
        self.asr_model = tk.StringVar(value="small")

        self._build()
        self.after(120, self._drain)

    # --- разметка окна ---------------------------------------------------------

    def _build(self) -> None:
        form = ttk.Frame(self, padding=PAD)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        self._folder_row(form, 0, "Папка с клипами", self.clips_dir)
        self._folder_row(form, 1, "Папка с озвучками", self.voice_dir)
        self._folder_row(form, 2, "Папка черновиков CapCut", self.drafts_dir, self._reload_templates)

        ttk.Label(form, text="Шаблоны").grid(row=3, column=0, sticky="nw", pady=(PAD, 0))
        holder = ttk.Frame(form)
        holder.grid(row=3, column=1, columnspan=2, sticky="ew", pady=(PAD, 0))
        holder.columnconfigure(0, weight=1)
        self.templates = tk.Listbox(holder, selectmode="extended", height=6, exportselection=False)
        self.templates.grid(row=0, column=0, sticky="ew")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.templates.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.templates.configure(yscrollcommand=scroll.set)
        ttk.Label(
            holder,
            text="Выдели нужные (Ctrl — по одному, Shift — диапазон). Ролики пойдут по кругу.",
            foreground="#666",
        ).grid(row=1, column=0, columnspan=2, sticky="w")

        options = ttk.Frame(form)
        options.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(PAD, 0))

        ttk.Label(options, text="Сколько роликов").pack(side="left")
        ttk.Spinbox(options, from_=1, to=999, width=6, textvariable=self.count).pack(side="left", padx=(4, PAD))

        ttk.Label(options, text="Кадров/с").pack(side="left")
        ttk.Combobox(options, width=5, textvariable=self.fps, values=("30", "60"),
                     state="readonly").pack(side="left", padx=(4, PAD))

        ttk.Label(options, text="Имена проектов").pack(side="left")
        ttk.Entry(options, width=10, textvariable=self.prefix).pack(side="left", padx=(4, PAD))

        ttk.Label(options, text="Зерно").pack(side="left")
        ttk.Entry(options, width=8, textvariable=self.seed).pack(side="left", padx=(4, PAD))

        ttk.Label(options, text="Распознавание").pack(side="left")
        ttk.Combobox(options, width=8, textvariable=self.asr_model, state="readonly",
                     values=("tiny", "base", "small", "medium")).pack(side="left", padx=(4, PAD))

        checks = ttk.Frame(form)
        checks.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        ttk.Checkbutton(checks, text="Собирать субтитры", variable=self.make_subtitles).pack(side="left")
        ttk.Checkbutton(checks, text="Убирать использованные материалы",
                        variable=self.consume).pack(side="left", padx=(PAD, 0))

        actions = ttk.Frame(self, padding=(PAD, 0))
        actions.pack(fill="x")
        self.start_button = ttk.Button(actions, text="Собрать", command=self._start)
        self.start_button.pack(side="left")
        ttk.Button(actions, text="Проверить окружение", command=self._doctor).pack(side="left", padx=PAD)
        ttk.Button(actions, text="Открыть журнал", command=self._open_log).pack(side="left")
        self.status = ttk.Label(actions, text="Готов")
        self.status.pack(side="right")

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=PAD, pady=(4, 0))

        self.output = tk.Text(self, wrap="word", height=20, state="disabled",
                              background="#101418", foreground="#d8dee4", insertbackground="#d8dee4")
        self.output.pack(fill="both", expand=True, padx=PAD, pady=PAD)
        self.output.tag_configure("error", foreground="#ff7b72")
        self.output.tag_configure("warning", foreground="#e3b341")

        self._reload_templates()

    def _folder_row(self, parent, row: int, label: str, variable: tk.StringVar, on_change=None) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=PAD, pady=2)

        def choose() -> None:
            picked = filedialog.askdirectory(initialdir=variable.get() or str(Path.home()))
            if picked:
                variable.set(picked)
                if on_change:
                    on_change()

        ttk.Button(parent, text="Выбрать…", command=choose).grid(row=row, column=2, pady=2)

    # --- действия --------------------------------------------------------------

    def _reload_templates(self) -> None:
        self.templates.delete(0, "end")
        folder = Path(self.drafts_dir.get())
        if not folder.is_dir():
            return
        for item in sorted(folder.iterdir()):
            if item.is_dir() and not item.name.startswith("."):
                self.templates.insert("end", item.name)

    def _collect(self) -> Config:
        chosen = [self.templates.get(i) for i in self.templates.curselection()]
        if not chosen:
            raise PipelineError("Не выбран ни один шаблон")
        if not Path(self.clips_dir.get()).is_dir():
            raise PipelineError("Не указана папка с клипами")
        if not Path(self.voice_dir.get()).is_dir():
            raise PipelineError("Не указана папка с озвучками")

        seed_text = self.seed.get().strip()
        return Config(
            clips_dir=Path(self.clips_dir.get()),
            voice_dir=Path(self.voice_dir.get()),
            drafts_dir=Path(self.drafts_dir.get()),
            templates=chosen,
            count=int(self.count.get()),
            seed=int(seed_text) if seed_text.isdigit() else None,
            fps=float(self.fps.get()),
            name_prefix=self.prefix.get().strip() or "auto",
            make_subtitles=bool(self.make_subtitles.get()),
            consume_inputs=bool(self.consume.get()),
            asr_model=self.asr_model.get(),
        )

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            config = self._collect()
        except PipelineError as exc:
            messagebox.showerror("Не хватает данных", str(exc))
            return

        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")
        self.progress.configure(maximum=config.count, value=0)
        self.start_button.configure(state="disabled")
        self.status.configure(text="Работаю…")

        self.log_path = logging_setup.setup(config.log_dir)
        logging_setup.add_handler(_configured(QueueHandler(self.messages)))

        def work() -> None:
            try:
                report = batch.run(config, progress=self._progress)
                self.messages.put((logging.INFO, "\n" + report.summary()))
            except PipelineError as exc:
                self.messages.put((logging.ERROR, str(exc)))
            except Exception as exc:  # noqa: BLE001
                self.messages.put((logging.ERROR, f"Неожиданная ошибка: {exc}"))
            finally:
                self.messages.put((logging.INFO, f"\nЖурнал: {self.log_path}"))
                self.messages.put((-1, ""))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _progress(self, done: int, total: int, message: str) -> None:
        self.messages.put((-2, f"{done}|{total}|{message}"))

    def _doctor(self) -> None:
        from .cli import _doctor as run_doctor

        try:
            config = Config(clips_dir=Path("."), voice_dir=Path("."), drafts_dir=Path(self.drafts_dir.get()))
            import io
            import contextlib

            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                run_doctor(config)
            messagebox.showinfo("Окружение", buffer.getvalue())
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Окружение", str(exc))

    def _open_log(self) -> None:
        if not self.log_path or not self.log_path.exists():
            messagebox.showinfo("Журнал", "Журнала пока нет — сначала запусти сборку")
            return
        import subprocess
        import sys

        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(self.log_path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(self.log_path)])
        else:
            subprocess.Popen(["xdg-open", str(self.log_path.parent)])

    # --- поток сообщений -------------------------------------------------------

    def _drain(self) -> None:
        while True:
            try:
                level, text = self.messages.get_nowait()
            except queue.Empty:
                break

            if level == -1:
                self.start_button.configure(state="normal")
                self.status.configure(text="Готов")
                continue
            if level == -2:
                done, total, message = text.split("|", 2)
                self.progress.configure(value=int(done) - 1, maximum=int(total))
                self.status.configure(text=message)
                continue

            tag = "error" if level >= logging.ERROR else "warning" if level >= logging.WARNING else ""
            self.output.configure(state="normal")
            self.output.insert("end", text + "\n", tag)
            self.output.see("end")
            self.output.configure(state="disabled")

        self.after(120, self._drain)


def _configured(handler: logging.Handler) -> logging.Handler:
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    return handler


def main() -> int:
    App().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
