"""Окно программы.

Сделано на tkinter, который входит в состав Python, — чтобы на Windows ничего
не пришлось доустанавливать. Две вкладки: сборка роликов по шаблонам и отдельная
нарезка видео на клипы. Работа идёт в фоновом потоке, журнал течёт в окно в
реальном времени.
"""
from __future__ import annotations

import contextlib
import io
import logging
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from . import batch, logging_setup, splitter
from .config import Config, _default_drafts_dir
from .errors import PipelineError

PAD = 8

# Служебные уровни для очереди сообщений.
DONE = -1
PROGRESS = -2


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
        self.geometry("1000x780")
        self.minsize(860, 640)

        self.messages: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.log_path: Path | None = None
        self._buttons: list[ttk.Button] = []

        notebook = ttk.Notebook(self)
        notebook.pack(fill="x", padx=PAD, pady=(PAD, 0))
        self.batch_tab = BatchTab(notebook, self)
        self.split_tab = SplitTab(notebook, self)
        notebook.add(self.batch_tab, text="  Сборка роликов  ")
        notebook.add(self.split_tab, text="  Нарезка видео  ")

        bottom = ttk.Frame(self, padding=(PAD, 4))
        bottom.pack(fill="x")
        button = ttk.Button(bottom, text="Открыть журнал", command=self._open_log)
        button.pack(side="left")
        self.status = ttk.Label(bottom, text="Готов")
        self.status.pack(side="right")

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=PAD)

        self.output = tk.Text(self, wrap="word", height=18, state="disabled",
                              background="#101418", foreground="#d8dee4", insertbackground="#d8dee4")
        self.output.pack(fill="both", expand=True, padx=PAD, pady=PAD)
        self.output.tag_configure("error", foreground="#ff7b72")
        self.output.tag_configure("warning", foreground="#e3b341")

        self.after(120, self._drain)

    # --- общее для вкладок -----------------------------------------------------

    def register(self, button: ttk.Button) -> None:
        self._buttons.append(button)

    def busy(self) -> bool:
        return bool(self.worker and self.worker.is_alive())

    def start(self, work: Callable[[], None], log_dir: Path, total: int) -> None:
        """Запускает работу в фоне, подключив журнал к окну."""
        if self.busy():
            return

        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")
        self.progress.configure(maximum=max(1, total), value=0)
        for button in self._buttons:
            button.configure(state="disabled")
        self.status.configure(text="Работаю…")

        self.log_path = logging_setup.setup(log_dir)
        handler = QueueHandler(self.messages)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logging_setup.add_handler(handler)

        def wrapper() -> None:
            try:
                work()
            except PipelineError as exc:
                self.messages.put((logging.ERROR, str(exc)))
            except Exception as exc:  # noqa: BLE001
                self.messages.put((logging.ERROR, f"Неожиданная ошибка: {exc}"))
            finally:
                self.messages.put((logging.INFO, f"\nЖурнал: {self.log_path}"))
                self.messages.put((DONE, ""))

        self.worker = threading.Thread(target=wrapper, daemon=True)
        self.worker.start()

    def progress_callback(self, done: int, total: int, message: str) -> None:
        self.messages.put((PROGRESS, f"{done}|{total}|{message}"))

    def say(self, text: str, level: int = logging.INFO) -> None:
        self.messages.put((level, text))

    def _open_log(self) -> None:
        if not self.log_path or not self.log_path.exists():
            messagebox.showinfo("Журнал", "Журнала пока нет — сначала что-нибудь запусти")
            return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(self.log_path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(self.log_path)])
        else:
            subprocess.Popen(["xdg-open", str(self.log_path.parent)])

    def _drain(self) -> None:
        while True:
            try:
                level, text = self.messages.get_nowait()
            except queue.Empty:
                break

            if level == DONE:
                for button in self._buttons:
                    button.configure(state="normal")
                self.status.configure(text="Готов")
                self.progress.configure(value=self.progress["maximum"])
                continue
            if level == PROGRESS:
                done, total, message = text.split("|", 2)
                self.progress.configure(value=int(done) - 1, maximum=max(1, int(total)))
                self.status.configure(text=message)
                continue

            tag = "error" if level >= logging.ERROR else "warning" if level >= logging.WARNING else ""
            self.output.configure(state="normal")
            self.output.insert("end", text + "\n", tag)
            self.output.see("end")
            self.output.configure(state="disabled")

        self.after(120, self._drain)


def folder_row(parent, row: int, label: str, variable: tk.StringVar, on_change=None) -> None:
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
    ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=PAD, pady=2)

    def choose() -> None:
        picked = filedialog.askdirectory(initialdir=variable.get() or str(Path.home()))
        if picked:
            variable.set(picked)
            if on_change:
                on_change()

    ttk.Button(parent, text="Выбрать…", command=choose).grid(row=row, column=2, pady=2)


class BatchTab(ttk.Frame):
    """Сборка роликов по шаблонам."""

    def __init__(self, parent, app: App):
        super().__init__(parent, padding=PAD)
        self.app = app

        self.clips_dir = tk.StringVar()
        self.clips_dir2 = tk.StringVar()
        self.voice_dir = tk.StringVar()
        self.drafts_dir = tk.StringVar(value=str(_default_drafts_dir()))
        self.count = tk.IntVar(value=10)
        self.seed = tk.StringVar()
        self.fps = tk.StringVar(value="60")
        self.prefix = tk.StringVar(value="auto")
        self.make_subtitles = tk.BooleanVar(value=True)
        self.consume = tk.BooleanVar(value=True)
        self.asr_model = tk.StringVar(value="small")

        self.columnconfigure(1, weight=1)
        folder_row(self, 0, "Папка с клипами", self.clips_dir)
        folder_row(self, 1, "И вторая, если надо", self.clips_dir2)
        ttk.Label(self, foreground="#666",
                  text="вторая нужна, когда короткие и длинные клипы разложены по разным папкам").grid(
            row=2, column=1, sticky="w", padx=PAD)
        folder_row(self, 3, "Папка с озвучками", self.voice_dir)
        folder_row(self, 4, "Папка черновиков CapCut", self.drafts_dir, self._reload)

        ttk.Label(self, text="Шаблоны").grid(row=5, column=0, sticky="nw", pady=(PAD, 0))
        holder = ttk.Frame(self)
        holder.grid(row=5, column=1, columnspan=2, sticky="ew", pady=(PAD, 0))
        holder.columnconfigure(0, weight=1)
        self.templates = tk.Listbox(holder, selectmode="extended", height=6, exportselection=False)
        self.templates.grid(row=0, column=0, sticky="ew")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.templates.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.templates.configure(yscrollcommand=scroll.set)
        ttk.Label(holder, foreground="#666",
                  text="Выдели нужные (Ctrl — по одному, Shift — диапазон). Ролики пойдут по кругу.").grid(
            row=1, column=0, columnspan=2, sticky="w")

        options = ttk.Frame(self)
        options.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(PAD, 0))
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

        checks = ttk.Frame(self)
        checks.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        ttk.Checkbutton(checks, text="Собирать субтитры", variable=self.make_subtitles).pack(side="left")
        ttk.Checkbutton(checks, text="Убирать использованные материалы",
                        variable=self.consume).pack(side="left", padx=(PAD, 0))

        actions = ttk.Frame(self)
        actions.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(PAD, 0))
        start = ttk.Button(actions, text="Собрать", command=self._start)
        start.pack(side="left")
        check = ttk.Button(actions, text="Проверить окружение", command=self._doctor)
        check.pack(side="left", padx=PAD)
        diag = ttk.Button(actions, text="Диагностика субтитров", command=self._diagnose)
        diag.pack(side="left")
        app.register(start)
        app.register(check)
        app.register(diag)

        self._reload()

    def _reload(self) -> None:
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
        folders = [Path(value) for value in (self.clips_dir.get().strip(), self.clips_dir2.get().strip()) if value]
        if not folders:
            raise PipelineError("Не указана папка с клипами")
        for folder in folders:
            if not folder.is_dir():
                raise PipelineError(f"Папка с клипами не найдена: {folder}")
        if not Path(self.voice_dir.get()).is_dir():
            raise PipelineError("Не указана папка с озвучками")

        seed_text = self.seed.get().strip()
        return Config(
            clips_dir=folders,
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
        try:
            config = self._collect()
        except PipelineError as exc:
            messagebox.showerror("Не хватает данных", str(exc))
            return

        def work() -> None:
            report = batch.run(config, progress=self.app.progress_callback)
            self.app.say("\n" + report.summary())

        self.app.start(work, config.log_dir, config.count)

    def _diagnose(self) -> None:
        """Сравнивает субтитры последнего собранного ролика с шаблоном."""
        from . import diagnose

        drafts = Path(self.drafts_dir.get())
        chosen = [self.templates.get(i) for i in self.templates.curselection()]
        if not chosen:
            messagebox.showinfo("Диагностика", "Выдели шаблон, по которому собирался ролик")
            return

        prefix = self.prefix.get().strip() or "auto"
        made = [
            item for item in drafts.iterdir()
            if item.is_dir() and item.name.startswith(prefix)
        ] if drafts.is_dir() else []
        if not made:
            messagebox.showinfo(
                "Диагностика",
                f"Не нашёл собранных роликов с именем на «{prefix}». Сначала собери хотя бы один.",
            )
            return

        clone = max(made, key=lambda item: item.stat().st_mtime)
        try:
            report = diagnose.compare(drafts / chosen[0], clone)
            path = diagnose.write_bundle(report, Path(self.drafts_dir.get()).parent / "диагностика")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Диагностика", str(exc))
            return

        self.app.say(report.describe())
        self.app.say(f"\nСлепок для разбора: {path}")
        messagebox.showinfo(
            "Диагностика",
            f"Проверен ролик {clone.name}.\n"
            f"Расхождений: {len(report.problems)}.\n\n"
            f"Подробности в окне ниже.\nФайл для пересылки:\n{path}",
        )

    def _doctor(self) -> None:
        from .cli import _doctor as run_doctor

        try:
            config = Config(clips_dir=Path("."), voice_dir=Path("."), drafts_dir=Path(self.drafts_dir.get()))
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                run_doctor(config)
            messagebox.showinfo("Окружение", buffer.getvalue())
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Окружение", str(exc))


class SplitTab(ttk.Frame):
    """Нарезка длинного видео на клипы. На сборку роликов не влияет."""

    def __init__(self, parent, app: App):
        super().__init__(parent, padding=PAD)
        self.app = app

        self.source = tk.StringVar()
        self.single_dir = tk.StringVar()
        self.trim_start = tk.StringVar(value="0")
        self.trim_end = tk.StringVar(value="0")
        self.pattern = tk.StringVar(value="4 15")
        self.per_length = tk.BooleanVar(value=True)
        self.keep_tail = tk.BooleanVar(value=False)
        self.reencode = tk.BooleanVar(value=True)
        self.length_dirs: dict[float, tk.StringVar] = {}

        self.columnconfigure(1, weight=1)

        ttk.Label(self, text="Видео").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(self, textvariable=self.source).grid(row=0, column=1, sticky="ew", padx=PAD, pady=2)
        ttk.Button(self, text="Выбрать…", command=self._pick_file).grid(row=0, column=2, pady=2)

        pattern_row = ttk.Frame(self)
        pattern_row.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(PAD, 0))
        ttk.Label(pattern_row, text="Длины фрагментов, с").pack(side="left")
        ttk.Entry(pattern_row, width=14, textvariable=self.pattern).pack(side="left", padx=(4, PAD))
        ttk.Label(pattern_row, foreground="#666",
                  text="одно число — все куски одинаковые; «4 15» — чередование 4, 15, 4, 15 до конца").pack(side="left")

        ttk.Checkbutton(self, text="Раскладывать по разным папкам: каждой длине своя",
                        variable=self.per_length).grid(row=2, column=0, columnspan=3,
                                                       sticky="w", pady=(PAD, 0))

        self.targets = ttk.Frame(self)
        self.targets.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.targets.columnconfigure(1, weight=1)

        trims = ttk.Frame(self)
        trims.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(PAD, 0))
        ttk.Label(trims, text="Отрезать с начала, с").pack(side="left")
        ttk.Entry(trims, width=7, textvariable=self.trim_start).pack(side="left", padx=(4, PAD))
        ttk.Label(trims, text="с конца, с").pack(side="left")
        ttk.Entry(trims, width=7, textvariable=self.trim_end).pack(side="left", padx=(4, PAD))

        checks = ttk.Frame(self)
        checks.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(PAD, 0))
        ttk.Checkbutton(checks, text="Оставить неполный остаток в конце",
                        variable=self.keep_tail).pack(side="left")
        ttk.Checkbutton(checks, text="Перекодировать (точная длина, но медленнее)",
                        variable=self.reencode).pack(side="left", padx=(PAD, 0))

        actions = ttk.Frame(self)
        actions.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(PAD, 0))
        preview = ttk.Button(actions, text="Посчитать", command=self._preview)
        preview.pack(side="left")
        start = ttk.Button(actions, text="Нарезать", command=self._start)
        start.pack(side="left", padx=PAD)
        app.register(preview)
        app.register(start)

        self.pattern.trace_add("write", self._rebuild_targets)
        self.per_length.trace_add("write", self._rebuild_targets)
        self._rebuild_targets()

    # --- папки вывода ----------------------------------------------------------

    def _base_dir(self) -> Path:
        source = self.source.get().strip()
        if source:
            return Path(source).parent / "клипы"
        return Path.home() / "клипы"

    def _suggest(self, length: float) -> str:
        return str(self._base_dir() / f"{length:g}s")

    def _rebuild_targets(self, *_) -> None:
        """Перестраивает строки выбора папок под текущую схему длин."""
        for child in self.targets.winfo_children():
            child.destroy()

        if not self.per_length.get():
            if not self.single_dir.get():
                self.single_dir.set(str(self._base_dir()))
            folder_row(self.targets, 0, "Куда складывать клипы", self.single_dir)
            return

        try:
            lengths = splitter.pattern_lengths(splitter.parse_pattern(self.pattern.get()))
        except PipelineError:
            ttk.Label(self.targets, foreground="#a05000",
                      text="Задай схему длин, и здесь появятся папки под каждую").grid(
                row=0, column=0, columnspan=3, sticky="w")
            return

        for row, length in enumerate(lengths):
            variable = self.length_dirs.get(length)
            if variable is None:
                variable = tk.StringVar(value=self._suggest(length))
                self.length_dirs[length] = variable
            elif not variable.get():
                variable.set(self._suggest(length))
            folder_row(self.targets, row, f"Клипы по {length:g} с", variable)

    def _pick_file(self) -> None:
        picked = filedialog.askopenfilename(
            title="Выбери видео",
            filetypes=[("Видео", "*.mp4 *.mov *.mkv *.avi *.m4v *.webm"), ("Все файлы", "*.*")],
        )
        if not picked:
            return
        self.source.set(picked)
        # Пустые поля заполняем подсказкой рядом с выбранным видео.
        if not self.single_dir.get():
            self.single_dir.set(str(self._base_dir()))
        for length, variable in self.length_dirs.items():
            if not variable.get():
                variable.set(self._suggest(length))
        self._rebuild_targets()

    def _values(self):
        source = Path(self.source.get())
        if not source.is_file():
            raise PipelineError("Не выбрано видео")
        pattern = splitter.parse_pattern(self.pattern.get())

        if self.per_length.get():
            folders: dict[float, Path] = {}
            for length in splitter.pattern_lengths(pattern):
                value = (self.length_dirs.get(length).get() if self.length_dirs.get(length) else "").strip()
                if not value:
                    raise PipelineError(f"Не указана папка для клипов по {length:g} с")
                folders[length] = Path(value)
            targets = folders
        else:
            value = self.single_dir.get().strip()
            if not value:
                raise PipelineError("Не указана папка, куда складывать клипы")
            targets = Path(value)

        def number(text: str, label: str) -> float:
            text = text.strip().replace(",", ".") or "0"
            try:
                value = float(text)
            except ValueError as exc:
                raise PipelineError(f"{label}: «{text}» не похоже на число секунд") from exc
            if value < 0:
                raise PipelineError(f"{label} не может быть отрицательной")
            return value

        return source, targets, pattern, number(self.trim_start.get(), "Обрезка с начала"), \
            number(self.trim_end.get(), "Обрезка с конца")

    def _preview(self) -> None:
        try:
            source, folders, pattern, start, end = self._values()
            resolved = splitter.resolve_targets(pattern, folders)
            from . import ffmpeg as ff

            duration = ff.probe(source).duration_s
            pieces, tail = splitter.plan_cuts(duration, pattern, start, end, self.keep_tail.get())
        except PipelineError as exc:
            messagebox.showerror("Нарезка", str(exc))
            return

        counts: dict[float, int] = {}
        for piece in pieces:
            counts[splitter.key(piece.requested_s)] = counts.get(splitter.key(piece.requested_s), 0) + 1

        lines = [
            f"Видео: {duration:.2f}с",
            f"После обрезки: {duration - start - end:.2f}с",
            "",
            f"Получится клипов: {len(pieces)}",
        ]
        for length in sorted(counts):
            lines.append(f"  по {length:g}с — {counts[length]} шт")
            lines.append(f"     {resolved[length]}")
        if tail > 0:
            lines.append("")
            lines.append(f"Остаток {tail:.2f}с будет отброшен")
        messagebox.showinfo("Что получится", "\n".join(lines))

    def _start(self) -> None:
        try:
            source, folders, pattern, start, end = self._values()
            resolved = splitter.resolve_targets(pattern, folders)
        except PipelineError as exc:
            messagebox.showerror("Нарезка", str(exc))
            return

        keep_tail = bool(self.keep_tail.get())
        reencode = bool(self.reencode.get())
        anchor = sorted(resolved.values())[0]
        log_dir = anchor.parent / "capcut_uniq_data" / "logs"

        def work() -> None:
            report = splitter.split(
                source, folders, pattern, start, end,
                keep_tail=keep_tail, reencode=reencode,
                progress=self.app.progress_callback,
            )
            self.app.say("\n" + report.summary())

        self.app.start(work, log_dir, 1)


def main() -> int:
    App().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
