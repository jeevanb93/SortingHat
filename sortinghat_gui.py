"""
Tkinter desktop front-end for SortingHat.

Architecture (see the Reporter seam in ``sortinghat.py``):

    SortingHatApp  ── owns the Tk widgets and the event loop
         │  observes
         ▼
    queue.Queue    ── the only thing crossing the thread boundary
         ▲  fills
         │
    GuiReporter    ── engine events → queue (Reporter implementation)
         ▲  emits
         │
    Controller     ── runs sort/undo on a worker thread; no widget knowledge

The engine does the real work and is never duplicated here: the GUI simply
supplies a different Reporter and renders the events it receives. Tk is not
thread-safe, so the worker only ever touches the queue, and every widget update
happens on the main thread as it drains that queue.
"""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from sortinghat import (
    Reporter,
    SortResult,
    UndoResult,
    build_ext_map,
    describe_undo_state,
    sort_directory,
    undo_last_sort,
)


APP_ID = "SortingHat.App"          # taskbar identity (see _apply_window_icon)
ICON_FILE = "assets/sortinghat.ico"


def resource_path(relative: str) -> Path:
    """Locate a bundled resource, whether running from source or a PyInstaller bundle."""
    base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)
    return Path(base) / relative


# ── Event plumbing ────────────────────────────────────────────────────────────

@dataclass
class Event:
    """A single engine event, queued for the UI thread."""
    kind: str
    data: dict = field(default_factory=dict)


class GuiReporter(Reporter):
    """Reporter that marshals engine events onto a thread-safe queue.

    It touches nothing but the queue, which is what makes it safe to run from the
    worker thread while the widgets live on the main thread.
    """

    def __init__(self, sink: "queue.Queue[Event]") -> None:
        self._sink = sink

    def _put(self, kind: str, /, **data: object) -> None:
        # `kind` is positional-only so an event may legitimately carry a data
        # field also called "kind" (the `ignored` event does) without clashing.
        self._sink.put(Event(kind, data))

    def moved(self, name, category, dest_name, renamed):
        self._put("moved", name=name, category=category, dest_name=dest_name, renamed=renamed)

    def previewed(self, name, category, dest_name, renamed):
        self._put("previewed", name=name, category=category, dest_name=dest_name, renamed=renamed)

    def skipped(self, name, reason):
        self._put("skipped", name=name, reason=reason)

    def excluded(self, name):
        self._put("excluded", name=name)

    def ignored(self, name, kind):
        self._put("ignored", name=name, kind=kind)

    def undo_started(self, count, timestamp, dry_run):
        self._put("undo_started", count=count, timestamp=timestamp, dry_run=dry_run)

    def restored(self, name, dest, dry_run):
        self._put("restored", name=name, dest=str(dest), dry_run=dry_run)

    def missing(self, name):
        self._put("missing", name=name)

    def blocked(self, name):
        self._put("blocked", name=name)

    def failed(self, name, error):
        self._put("failed", name=name, error=error)

    def no_undo_log(self, target_dir):
        self._put("no_undo_log", target=str(target_dir))

    def undo_summary(self, result):
        self._put("undo_summary", result=result)

    def progress(self, done, total):
        self._put("progress", done=done, total=total)

    def note(self, message):
        self._put("note", message=message)


class Controller:
    """Runs engine operations on a background thread and reports through a queue.

    Deliberately holds no reference to any widget: the UI observes results only by
    draining the shared queue, so this class can be unit-tested without a display.
    """

    def __init__(self, sink: "queue.Queue[Event]") -> None:
        self.queue = sink
        self.reporter = GuiReporter(sink)
        self._busy = threading.Lock()

    def is_busy(self) -> bool:
        return self._busy.locked()

    def run_sort(self, target: Path, dry_run: bool, ext_map: dict | None = None) -> bool:
        return self._start(self._sort, target, dry_run, ext_map)

    def run_undo(self, target: Path, dry_run: bool) -> bool:
        return self._start(self._undo, target, dry_run)

    # ── internals ──

    def _start(self, fn, *args) -> bool:
        """Launch *fn* on a worker thread unless one is already running."""
        if not self._busy.acquire(blocking=False):
            return False
        threading.Thread(target=self._run, args=(fn, args), daemon=True).start()
        return True

    def _run(self, fn, args) -> None:
        try:
            fn(*args)
        except Exception as exc:  # surface unexpected engine errors to the log rather than dying silently
            self.queue.put(Event("error", {"message": str(exc)}))
        finally:
            self._busy.release()
            self.queue.put(Event("done", {}))

    def _sort(self, target: Path, dry_run: bool, ext_map: dict | None) -> None:
        result = sort_directory(target, dry_run=dry_run, ext_map=ext_map, reporter=self.reporter)
        self.queue.put(Event("sort_finished", {"result": result, "dry_run": dry_run}))

    def _undo(self, target: Path, dry_run: bool) -> None:
        result = undo_last_sort(target, dry_run=dry_run, reporter=self.reporter)
        self.queue.put(Event("undo_finished", {"result": result, "dry_run": dry_run}))


# ── Application window ─────────────────────────────────────────────────────────

class SortingHatApp(tk.Tk):
    """The main window. Builds widgets, owns the loop, and drains the queue."""

    POLL_MS = 50  # how often the UI thread checks the queue

    # log line colouring, mirroring the terminal palette
    _LOG_TAGS = {
        "ok":      "#2e9c48",
        "warn":    "#b8860b",
        "error":   "#c0392b",
        "preview": "#1f8fb0",
        "muted":   "#888888",
    }

    def __init__(self, target: Path | None = None) -> None:
        super().__init__()
        self.title("SortingHat")
        self.geometry("760x560")
        self.minsize(600, 440)

        self.target: Path = (target or Path.home() / "Downloads").resolve()
        self.ext_map = build_ext_map()
        self.queue: "queue.Queue[Event]" = queue.Queue()
        self.controller = Controller(self.queue)

        self._apply_window_icon()
        self._build_widgets()
        self._refresh_header()
        self.after(self.POLL_MS, self._drain_queue)

    def _apply_window_icon(self) -> None:
        """Set the taskbar/title-bar icon, degrading silently if it isn't available."""
        # Tell Windows this is its own app, so the taskbar shows our icon and doesn't
        # fold the window in under the generic Python launcher's icon.
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
            except Exception:
                pass
        icon = resource_path(ICON_FILE)
        if icon.exists():
            try:
                self.iconbitmap(str(icon))
            except tk.TclError:
                pass  # platform without .ico support — window just uses the default icon

    # ── layout ──

    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 6}

        header = ttk.Frame(self)
        header.pack(fill="x", **pad)
        ttk.Label(header, text="Folder:").pack(side="left")
        self.target_var = tk.StringVar()
        ttk.Label(header, textvariable=self.target_var, foreground="#1f8fb0").pack(side="left", padx=(4, 0))
        ttk.Button(header, text="Change…", command=self.on_change_folder).pack(side="right")

        actions = ttk.Frame(self)
        actions.pack(fill="x", **pad)
        self.preview_btn = ttk.Button(actions, text="Preview", command=self.on_preview)
        self.sort_btn    = ttk.Button(actions, text="Sort now", command=self.on_sort)
        self.undo_btn    = ttk.Button(actions, text="Undo", command=self.on_undo)
        self.preview_btn.pack(side="left")
        self.sort_btn.pack(side="left", padx=6)
        self.undo_btn.pack(side="left")
        self.undo_var = tk.StringVar()
        ttk.Label(actions, textvariable=self.undo_var, foreground="#888888").pack(side="right")

        body = ttk.Panedwindow(self, orient="vertical")
        body.pack(fill="both", expand=True, **pad)

        # preview / results table
        table_frame = ttk.Frame(body)
        self.tree = ttk.Treeview(table_frame, columns=("file", "category"), show="headings", height=10)
        self.tree.heading("file", text="File")
        self.tree.heading("category", text="→ Category")
        self.tree.column("file", width=440, anchor="w")
        self.tree.column("category", width=160, anchor="w")
        tree_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        body.add(table_frame, weight=3)

        # log pane
        log_frame = ttk.Frame(body)
        self.log = tk.Text(log_frame, height=8, wrap="none", state="disabled",
                           background="#1e1e1e", foreground="#dddddd", relief="flat")
        for tag, colour in self._LOG_TAGS.items():
            self.log.tag_configure(tag, foreground=colour)
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")
        body.add(log_frame, weight=2)

        footer = ttk.Frame(self)
        footer.pack(fill="x", **pad)
        self.progress = ttk.Progressbar(footer, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(footer, textvariable=self.status_var).pack(side="right", padx=(8, 0))

    # ── header / small helpers ──

    def _refresh_header(self) -> None:
        self.target_var.set(str(self.target))
        self.undo_var.set(f"Undo: {describe_undo_state(self.target)}")

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for btn in (self.preview_btn, self.sort_btn, self.undo_btn):
            btn.configure(state=state)

    def _clear_results(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.progress.configure(value=0)

    def _log(self, text: str, tag: str = "") -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    # ── button handlers ──

    def on_change_folder(self) -> None:
        chosen = filedialog.askdirectory(initialdir=str(self.target), title="Choose a folder to organize")
        if chosen:
            self.target = Path(chosen).resolve()
            self._refresh_header()
            self.status_var.set("Target changed.")

    def on_preview(self) -> None:
        self._begin("Previewing…")
        self.controller.run_sort(self.target, dry_run=True, ext_map=self.ext_map)

    def on_sort(self) -> None:
        if not messagebox.askyesno("Sort now", f"Move files in\n{self.target}\ninto category folders?"):
            return
        self._begin("Sorting…")
        self.controller.run_sort(self.target, dry_run=False, ext_map=self.ext_map)

    def on_undo(self) -> None:
        self._begin("Undoing…")
        self.controller.run_undo(self.target, dry_run=False)

    def _begin(self, status: str) -> None:
        if self.controller.is_busy():
            return
        self._clear_results()
        self._set_busy(True)
        self.status_var.set(status)

    # ── queue draining (main thread only) ──

    def _drain_queue(self) -> None:
        try:
            while True:
                self._handle(self.queue.get_nowait())
        except queue.Empty:
            pass
        self.after(self.POLL_MS, self._drain_queue)

    def _handle(self, ev: Event) -> None:
        handler = getattr(self, f"_on_{ev.kind}", None)
        if handler:
            handler(**ev.data)

    # ── event handlers ──

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.configure(maximum=max(total, 1), value=done)

    def _on_previewed(self, name, category, dest_name, renamed):
        self.tree.insert("", "end", values=(name, category))
        note = "  (renamed)" if renamed else ""
        self._log(f"[preview] {name} -> {category}/{dest_name}{note}", "preview")

    def _on_moved(self, name, category, dest_name, renamed):
        self.tree.insert("", "end", values=(name, category))
        note = "  (renamed)" if renamed else ""
        self._log(f"moved {name} -> {category}/{dest_name}{note}", "ok")

    def _on_skipped(self, name, reason):
        self._log(f"[skipped] {name}: {reason}", "error")

    def _on_excluded(self, name):
        self._log(f"[excluded] {name}", "warn")

    def _on_ignored(self, name, kind):
        self._log(f"[{kind}] {name}", "muted")

    def _on_undo_started(self, count, timestamp, dry_run):
        verb = "Would undo" if dry_run else "Undoing"
        self._log(f"{verb} {count} move(s) from {timestamp}", "muted")

    def _on_restored(self, name, dest, dry_run):
        verb = "would restore" if dry_run else "restored"
        self._log(f"{verb} {name} -> {dest}", "ok")

    def _on_missing(self, name):
        self._log(f"[missing] {name}", "warn")

    def _on_blocked(self, name):
        self._log(f"[blocked] refusing to restore outside target: {name}", "error")

    def _on_failed(self, name, error):
        self._log(f"[failed] {name}: {error}", "error")

    def _on_no_undo_log(self, target):
        self._log("Nothing to undo in this folder.", "muted")

    def _on_note(self, message):
        self._log(message, "muted")

    def _on_error(self, message):
        self._log(f"Error: {message}", "error")

    def _on_sort_finished(self, result: SortResult, dry_run: bool):
        verb = "Would move" if dry_run else "Moved"
        parts = ", ".join(f"{cat} {n}" for cat, n in sorted(result.category_counts.items()))
        self.status_var.set(f"{verb} {result.moved} file(s)." + (f"  [{parts}]" if parts else ""))

    def _on_undo_finished(self, result: UndoResult, dry_run: bool):
        verb = "Would restore" if result.dry_run else "Restored"
        self.status_var.set(f"{verb} {result.restored} file(s).")
        self._refresh_header()  # undo stack changed

    def _on_done(self):
        self._set_busy(False)


# ── Entry point ───────────────────────────────────────────────────────────────

def main(target: Path | None = None) -> None:
    app = SortingHatApp(target)
    app.mainloop()


if __name__ == "__main__":
    main()
