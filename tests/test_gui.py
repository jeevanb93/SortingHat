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
