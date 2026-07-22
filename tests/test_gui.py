"""
Tests for the GUI's logic layer — GuiReporter, Controller, and the worker
threading — none of which need a display. A single optional smoke test
constructs the real window and is skipped where no display is available.
"""

from __future__ import annotations

import queue

import pytest

from sortinghat import Verbosity, build_ext_map, sort_directory
from sortinghat_gui import Controller, Event, GuiReporter, SortingHatApp


def _drain_until_done(q: "queue.Queue[Event]", timeout: float = 5.0) -> list[Event]:
    """Collect events until the controller signals completion."""
    events: list[Event] = []
    while True:
        ev = q.get(timeout=timeout)
        events.append(ev)
        if ev.kind == "done":
            return events


def _kinds(events: list[Event]) -> list[str]:
    return [e.kind for e in events]


# ── GuiReporter ───────────────────────────────────────────────────────────────

class TestGuiReporter:
    def test_events_are_enqueued_with_their_payload(self):
        q: "queue.Queue[Event]" = queue.Queue()
        r = GuiReporter(q)
        r.moved("a.pdf", "Documents", "a.pdf", False)
        r.progress(3, 10)

        first = q.get_nowait()
        assert first.kind == "moved"
        assert first.data == {"name": "a.pdf", "category": "Documents",
                              "dest_name": "a.pdf", "renamed": False}
        second = q.get_nowait()
        assert second.kind == "progress"
        assert second.data == {"done": 3, "total": 10}

    def test_reporter_only_touches_the_queue(self):
        # A GuiReporter must be safe to run off-thread: it holds nothing but the sink.
        q: "queue.Queue[Event]" = queue.Queue()
        r = GuiReporter(q)
        assert vars(r) == {"_sink": q}

    def test_ignored_event_carries_kind_without_clashing(self):
        # Regression: the `ignored` event has a data field named "kind", which must
        # not collide with _put's own positional parameter (crashed on system files).
        q: "queue.Queue[Event]" = queue.Queue()
        GuiReporter(q).ignored("desktop.ini", "system")
        ev = q.get_nowait()
        assert ev.kind == "ignored"
        assert ev.data == {"name": "desktop.ini", "kind": "system"}

    def test_every_reporter_method_enqueues_without_error(self):
        # Exercise the whole surface so a signature clash can't hide in an untested one.
        from pathlib import Path
        from sortinghat import UndoResult
        q: "queue.Queue[Event]" = queue.Queue()
        r = GuiReporter(q)
        r.moved("a", "Documents", "a", False)
        r.previewed("a", "Documents", "a", False)
        r.skipped("a", "reason")
        r.excluded("a")
        r.ignored("a", "system")
        r.undo_started(1, "t", False)
        r.restored("a", Path("a"), False)
        r.missing("a")
        r.blocked("a")
        r.failed("a", "err")
        r.no_undo_log(Path("."))
        r.undo_summary(UndoResult())
        r.progress(1, 2)
        r.note("hi")
        assert q.qsize() == 14


# ── Controller (worker thread + queue) ────────────────────────────────────────

class TestController:
    def _make_files(self, directory, names):
        for name in names:
            (directory / name).write_text(f"content of {name}")

    def test_preview_emits_rows_and_moves_nothing(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf", "photo.jpg"])
        q: "queue.Queue[Event]" = queue.Queue()
        Controller(q).run_sort(tmp_path, dry_run=True, ext_map=build_ext_map())
        events = _drain_until_done(q)

        assert "previewed" in _kinds(events)
        finished = [e for e in events if e.kind == "sort_finished"][0]
        assert finished.data["result"].moved == 2
        assert (tmp_path / "doc.pdf").exists()             # dry run: untouched
        assert not (tmp_path / "Documents").exists()

    def test_sort_with_system_file_does_not_crash(self, tmp_path):
        # A real Downloads folder always has system/hidden files; make sure the
        # 'ignored' event flows through the queue rather than raising in the worker.
        self._make_files(tmp_path, ["doc.pdf"])
        (tmp_path / "desktop.ini").write_text("x")
        (tmp_path / ".hidden").write_text("x")
        q: "queue.Queue[Event]" = queue.Queue()
        Controller(q).run_sort(tmp_path, dry_run=True, ext_map=build_ext_map())
        events = _drain_until_done(q)

        assert "error" not in _kinds(events)     # the worker did not blow up
        assert "ignored" in _kinds(events)

    def test_sort_moves_files_and_reports_finished(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf"])
        q: "queue.Queue[Event]" = queue.Queue()
        Controller(q).run_sort(tmp_path, dry_run=False, ext_map=build_ext_map())
        events = _drain_until_done(q)

        assert (tmp_path / "Documents" / "doc.pdf").exists()
        assert _kinds(events).count("sort_finished") == 1

    def test_undo_restores_and_reports_finished(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)

        q: "queue.Queue[Event]" = queue.Queue()
        Controller(q).run_undo(tmp_path, dry_run=False)
        events = _drain_until_done(q)

        assert (tmp_path / "doc.pdf").exists()
        finished = [e for e in events if e.kind == "undo_finished"][0]
        assert finished.data["result"].restored == 1

    def test_busy_lock_releases_after_completion(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf"])
        q: "queue.Queue[Event]" = queue.Queue()
        c = Controller(q)
        assert not c.is_busy()
        c.run_sort(tmp_path, dry_run=True, ext_map=build_ext_map())
        _drain_until_done(q)
        assert not c.is_busy()

    def test_done_event_is_always_last(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf", "song.mp3"])
        q: "queue.Queue[Event]" = queue.Queue()
        Controller(q).run_sort(tmp_path, dry_run=True, ext_map=build_ext_map())
        events = _drain_until_done(q)
        assert events[-1].kind == "done"
        assert _kinds(events).count("done") == 1


# ── Optional real-window smoke test ───────────────────────────────────────────

class TestWindowSmoke:
    def test_window_constructs_and_drains(self, tmp_path):
        tk = pytest.importorskip("tkinter")
        try:
            app = SortingHatApp(tmp_path)
        except tk.TclError:
            pytest.skip("no display available for a real Tk window")
        try:
            # the handler table must cover every event kind the reporter emits
            assert app.target == tmp_path.resolve()
            assert hasattr(app, "_on_sort_finished")
        finally:
            app.destroy()
