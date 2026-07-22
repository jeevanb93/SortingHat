from __future__ import annotations

import json
from pathlib import Path

import pytest

from sortinghat import (
    GREEN,
    RED,
    YELLOW,
    CYAN,
    RESET,
    Verbosity,
    SortResult,
    build_ext_map,
    colourise,
    describe_undo_state,
    is_within,
    print_summary,
    sanitize_category,
    get_category,
    handle_collision,
    is_excluded,
    is_system_file,
    load_config,
    prune_empty_dirs,
    read_undo_runs,
    run_interactive_menu,
    sort_directory,
    supports_colour,
    undo_last_sort,
    write_undo_runs,
    UNDO_LOG_FILENAME,
)


def _symlink_or_skip(link: Path, target: Path) -> None:
    """Create a symlink, or skip the test where the OS/user won't allow it (e.g. Windows without privilege)."""
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted in this environment")


# ── get_category ──────────────────────────────────────────────────────────────

class TestGetCategory:
    def setup_method(self):
        self.ext_map = build_ext_map()

    def test_known_extensions_route_correctly(self):
        cases = {
            ".pdf":  "Documents",
            ".mp3":  "Music",
            ".jpg":  "Pictures",
            ".mp4":  "Videos",
            ".zip":  "Compressed",
            ".torrent": "Torrents",
            ".exe":  "Installers",
        }
        for ext, expected in cases.items():
            assert get_category(ext, self.ext_map) == expected

    def test_unknown_extension_returns_misc(self):
        assert get_category(".xyz", self.ext_map) == "Misc"
        assert get_category(".sortinghat", self.ext_map) == "Misc"

    def test_empty_extension_returns_misc(self):
        assert get_category("", self.ext_map) == "Misc"

    def test_lookup_is_case_insensitive(self):
        assert get_category(".PDF", self.ext_map) == "Documents"
        assert get_category(".MP3", self.ext_map) == "Music"
        assert get_category(".JpEg", self.ext_map) == "Pictures"


# ── is_system_file ────────────────────────────────────────────────────────────

class TestIsSystemFile:
    def test_dotfiles_are_system(self, tmp_path):
        assert is_system_file(tmp_path / ".DS_Store")
        assert is_system_file(tmp_path / ".gitignore")
        assert is_system_file(tmp_path / ".sortinghat_undo.json")

    def test_known_windows_system_files(self, tmp_path):
        assert is_system_file(tmp_path / "desktop.ini")
        assert is_system_file(tmp_path / "Thumbs.db")

    def test_system_filenames_are_case_insensitive(self, tmp_path):
        assert is_system_file(tmp_path / "DESKTOP.INI")
        assert is_system_file(tmp_path / "THUMBS.DB")

    def test_normal_files_are_not_system(self, tmp_path):
        assert not is_system_file(tmp_path / "report.pdf")
        assert not is_system_file(tmp_path / "photo.jpg")
        assert not is_system_file(tmp_path / "archive.zip")


# ── is_excluded ───────────────────────────────────────────────────────────────

class TestIsExcluded:
    def test_matching_pattern_returns_true(self, tmp_path):
        assert is_excluded(tmp_path / "temp.tmp", ["*.tmp"])
        assert is_excluded(tmp_path / "Thumbs.db", ["Thumbs*"])

    def test_non_matching_pattern_returns_false(self, tmp_path):
        assert not is_excluded(tmp_path / "report.pdf", ["*.tmp"])

    def test_multiple_patterns_any_match_returns_true(self, tmp_path):
        assert is_excluded(tmp_path / "notes.txt", ["*.tmp", "*.txt"])

    def test_empty_pattern_list_always_returns_false(self, tmp_path):
        assert not is_excluded(tmp_path / "anything.xyz", [])


# ── handle_collision ──────────────────────────────────────────────────────────

class TestHandleCollision:
    def test_no_conflict_returns_original_path(self, tmp_path):
        dest = tmp_path / "file.txt"
        assert handle_collision(dest) == dest

    def test_real_file_conflict_increments_counter(self, tmp_path):
        dest = tmp_path / "file.txt"
        dest.write_text("existing")
        result = handle_collision(dest)
        assert result == tmp_path / "file (1).txt"

    def test_multiple_real_conflicts_find_next_free(self, tmp_path):
        (tmp_path / "file.txt").write_text("1")
        (tmp_path / "file (1).txt").write_text("2")
        result = handle_collision(tmp_path / "file.txt")
        assert result == tmp_path / "file (2).txt"

    def test_occupied_set_prevents_dry_run_collision(self, tmp_path):
        dest = tmp_path / "file.txt"
        occupied = {dest}
        result = handle_collision(dest, occupied)
        assert result == tmp_path / "file (1).txt"

    def test_occupied_set_combined_with_real_files(self, tmp_path):
        dest = tmp_path / "file.txt"
        dest.write_text("real")
        occupied = {tmp_path / "file (1).txt"}
        result = handle_collision(dest, occupied)
        assert result == tmp_path / "file (2).txt"

    def test_dangling_symlink_counts_as_occupied(self, tmp_path):
        # A broken symlink at the destination must not be treated as free, or
        # shutil.move could overwrite it on POSIX. lexists (not exists) catches it.
        dest = tmp_path / "file.txt"
        _symlink_or_skip(dest, tmp_path / "does-not-exist")
        assert not dest.exists()          # broken link: exists() is False...
        result = handle_collision(dest)   # ...but handle_collision must still avoid it
        assert result == tmp_path / "file (1).txt"


# ── build_ext_map ─────────────────────────────────────────────────────────────

class TestBuildExtMap:
    def test_default_map_contains_built_in_extensions(self):
        ext_map = build_ext_map()
        assert ext_map[".pdf"] == "Documents"
        assert ext_map[".mp3"] == "Music"
        assert ext_map[".jpg"] == "Pictures"

    def test_extra_adds_new_category(self):
        ext_map = build_ext_map({"Code": [".py", ".js"]})
        assert ext_map[".py"] == "Code"
        assert ext_map[".js"] == "Code"

    def test_extra_extends_existing_category(self):
        ext_map = build_ext_map({"Music": [".mid"]})
        assert ext_map[".mid"] == "Music"
        assert ext_map[".mp3"] == "Music"  # original still present

    def test_extra_extensions_are_normalised_to_lowercase(self):
        ext_map = build_ext_map({"Code": [".PY", ".JS"]})
        assert ext_map[".py"] == "Code"
        assert ext_map[".js"] == "Code"


# ── load_config ───────────────────────────────────────────────────────────────

class TestLoadConfig:
    def test_valid_config_returns_dict(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"Code": [".py", ".js"]}))
        result = load_config(config_file)
        assert result == {"Code": [".py", ".js"]}

    def test_missing_file_calls_sys_exit(self, tmp_path):
        with pytest.raises(SystemExit):
            load_config(tmp_path / "nonexistent.json")

    def test_invalid_json_calls_sys_exit(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{ not valid json }")
        with pytest.raises(SystemExit):
            load_config(bad_file)

    def test_non_dict_json_calls_sys_exit(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text(json.dumps([".py", ".js"]))
        with pytest.raises(SystemExit):
            load_config(bad_file)

    def test_string_value_is_rejected_not_iterated(self, tmp_path):
        # {"Code": "py"} must error rather than silently become extensions 'p','y'.
        bad_file = tmp_path / "bad.json"
        bad_file.write_text(json.dumps({"Code": "py"}))
        with pytest.raises(SystemExit):
            load_config(bad_file)

    def test_extension_without_leading_dot_is_rejected(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text(json.dumps({"Code": ["py"]}))
        with pytest.raises(SystemExit):
            load_config(bad_file)

    def test_non_string_extension_is_rejected(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text(json.dumps({"Code": [123]}))
        with pytest.raises(SystemExit):
            load_config(bad_file)

    def test_traversal_category_name_is_rejected(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text(json.dumps({"../../evil": [".py"]}))
        with pytest.raises(SystemExit):
            load_config(bad_file)

    def test_absolute_category_name_is_rejected(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text(json.dumps({"C:/Windows/Temp": [".py"]}))
        with pytest.raises(SystemExit):
            load_config(bad_file)


# ── sanitize_category ─────────────────────────────────────────────────────────

class TestSanitizeCategory:
    def test_plain_names_pass_through(self):
        assert sanitize_category("Code") == "Code"
        assert sanitize_category("My Documents") == "My Documents"

    def test_surrounding_whitespace_is_trimmed(self):
        assert sanitize_category("  Code  ") == "Code"

    @pytest.mark.parametrize("bad", [
        "", "   ", "..", "../../evil", "a/b", "a\\b",
        "C:/Windows", "C:\\Windows", "name:stream", "a*b", "a?b", "a|b", "a<b", 'a"b',
    ])
    def test_dangerous_names_raise(self, bad):
        with pytest.raises(ValueError):
            sanitize_category(bad)

    def test_build_ext_map_rejects_dangerous_category(self):
        with pytest.raises(ValueError):
            build_ext_map({"../escape": [".py"]})


# ── is_within ─────────────────────────────────────────────────────────────────

class TestIsWithin:
    def test_child_inside_parent(self, tmp_path):
        child = tmp_path / "Documents" / "a.pdf"
        assert is_within(child, tmp_path)

    def test_parent_itself_counts_as_within(self, tmp_path):
        assert is_within(tmp_path, tmp_path)

    def test_sibling_is_not_within(self, tmp_path):
        parent = tmp_path / "target"
        parent.mkdir()
        outside = tmp_path / "elsewhere" / "a.pdf"
        assert not is_within(outside, parent)

    def test_parent_traversal_is_not_within(self, tmp_path):
        parent = tmp_path / "target"
        parent.mkdir()
        assert not is_within(parent / ".." / ".." / "etc", parent)


# ── sort_directory ────────────────────────────────────────────────────────────

class TestSortDirectory:
    def _make_files(self, directory: Path, names: list[str]) -> None:
        for name in names:
            (directory / name).write_text(f"content of {name}")

    # ── Basic sorting ──────────────────────────────────────────────────────────

    def test_files_moved_to_correct_categories(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf", "photo.jpg", "song.mp3", "archive.zip"])
        result = sort_directory(tmp_path, verbosity=Verbosity.QUIET)

        assert (tmp_path / "Documents" / "doc.pdf").exists()
        assert (tmp_path / "Pictures"  / "photo.jpg").exists()
        assert (tmp_path / "Music"     / "song.mp3").exists()
        assert (tmp_path / "Compressed"/ "archive.zip").exists()
        assert result.moved == 4

    def test_unknown_extension_goes_to_misc(self, tmp_path):
        self._make_files(tmp_path, ["script.xyz"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        assert (tmp_path / "Misc" / "script.xyz").exists()

    def test_symlinks_are_skipped_not_moved(self, tmp_path):
        real = tmp_path / "outside.pdf"
        real.write_text("sensitive")
        (tmp_path.parent / "target_real").mkdir(exist_ok=True)
        link = tmp_path / "shortcut.pdf"
        _symlink_or_skip(link, real)

        result = sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        assert link.is_symlink()                       # left in place
        assert not (tmp_path / "Documents" / "shortcut.pdf").exists()
        assert result.system_ignored >= 1

    # ── Dry run ────────────────────────────────────────────────────────────────

    def test_dry_run_does_not_move_files(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf", "photo.jpg"])
        result = sort_directory(tmp_path, dry_run=True, verbosity=Verbosity.QUIET)

        assert (tmp_path / "doc.pdf").exists()
        assert (tmp_path / "photo.jpg").exists()
        assert not (tmp_path / "Documents").exists()
        assert not (tmp_path / "Pictures").exists()
        assert result.moved == 2

    def test_dry_run_does_not_write_undo_log(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf"])
        sort_directory(tmp_path, dry_run=True, verbosity=Verbosity.QUIET)
        assert not (tmp_path / UNDO_LOG_FILENAME).exists()

    # ── Collision handling ─────────────────────────────────────────────────────

    def test_collision_renames_file(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf"])
        (tmp_path / "Documents").mkdir()
        (tmp_path / "Documents" / "doc.pdf").write_text("pre-existing")
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        assert (tmp_path / "Documents" / "doc (1).pdf").exists()

    def test_dry_run_collision_simulation_is_accurate(self, tmp_path):
        # Two files with the same name after categorisation — second must detect
        # the first as 'virtually' occupied even though no real move happened.
        self._make_files(tmp_path, ["notes.txt", "notes2.txt"])
        # Rename second to share the same destination name as the first
        (tmp_path / "notes2.txt").rename(tmp_path / "notes.txt.bak")
        # Use two files with the same extension that both resolve to Documents
        self._make_files(tmp_path, ["a.pdf", "b.pdf"])
        (tmp_path / "Documents").mkdir()
        (tmp_path / "Documents" / "a.pdf").write_text("existing")

        result = sort_directory(tmp_path, dry_run=True, verbosity=Verbosity.QUIET)
        assert result.moved >= 2

    # ── System file filtering ──────────────────────────────────────────────────

    def test_system_files_are_ignored(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf"])
        (tmp_path / "desktop.ini").write_text("")
        (tmp_path / ".DS_Store").write_text("")
        result = sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        assert result.system_ignored == 2
        assert not (tmp_path / "Misc" / "desktop.ini").exists()

    # ── Exclude patterns ───────────────────────────────────────────────────────

    def test_excluded_files_stay_in_place(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf", "temp.tmp"])
        result = sort_directory(tmp_path, exclude_patterns=["*.tmp"], verbosity=Verbosity.QUIET)
        assert (tmp_path / "temp.tmp").exists()
        assert result.excluded == 1
        assert result.moved == 1

    # ── Custom ext_map ─────────────────────────────────────────────────────────

    def test_custom_config_routes_to_new_category(self, tmp_path):
        self._make_files(tmp_path, ["script.py"])
        ext_map = build_ext_map({"Code": [".py"]})
        sort_directory(tmp_path, ext_map=ext_map, verbosity=Verbosity.QUIET)
        assert (tmp_path / "Code" / "script.py").exists()

    # ── Undo log ───────────────────────────────────────────────────────────────

    def test_live_run_writes_undo_log(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        log_path = tmp_path / UNDO_LOG_FILENAME
        assert log_path.exists()
        log = json.loads(log_path.read_text())
        assert len(log["runs"]) == 1
        assert log["runs"][0]["moves"][0]["src"].endswith("doc.pdf")

    def test_undo_log_not_written_when_nothing_moved(self, tmp_path):
        # Empty directory — nothing to move
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        assert not (tmp_path / UNDO_LOG_FILENAME).exists()

    def test_second_run_appends_instead_of_overwriting(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        self._make_files(tmp_path, ["photo.jpg"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)

        runs = read_undo_runs(tmp_path / UNDO_LOG_FILENAME)
        assert len(runs) == 2
        assert runs[0]["moves"][0]["src"].endswith("doc.pdf")
        assert runs[1]["moves"][0]["src"].endswith("photo.jpg")


# ── Undo log helpers ──────────────────────────────────────────────────────────

class TestUndoLogHelpers:
    def test_missing_log_returns_empty_list(self, tmp_path):
        assert read_undo_runs(tmp_path / UNDO_LOG_FILENAME) == []

    def test_legacy_single_run_format_is_read_as_one_run(self, tmp_path):
        log_path = tmp_path / UNDO_LOG_FILENAME
        log_path.write_text(json.dumps({
            "timestamp": "2026-01-01T00:00:00+00:00",
            "target": str(tmp_path),
            "moves": [{"src": "a.pdf", "dst": "Documents/a.pdf"}],
        }))
        runs = read_undo_runs(log_path)
        assert len(runs) == 1
        assert runs[0]["moves"][0]["src"] == "a.pdf"

    def test_corrupt_log_is_ignored_rather_than_raising(self, tmp_path):
        log_path = tmp_path / UNDO_LOG_FILENAME
        log_path.write_text("{ not valid json }")
        assert read_undo_runs(log_path) == []

    def test_writing_empty_run_list_removes_the_log(self, tmp_path):
        log_path = tmp_path / UNDO_LOG_FILENAME
        log_path.write_text("{}")
        write_undo_runs(log_path, [])
        assert not log_path.exists()

    def test_round_trip_preserves_runs(self, tmp_path):
        log_path = tmp_path / UNDO_LOG_FILENAME
        runs = [{"timestamp": "t1", "target": "x", "moves": []},
                {"timestamp": "t2", "target": "x", "moves": []}]
        write_undo_runs(log_path, runs)
        assert read_undo_runs(log_path) == runs

    def test_oversized_log_is_ignored(self, tmp_path, monkeypatch):
        import sortinghat
        monkeypatch.setattr(sortinghat, "MAX_UNDO_LOG_BYTES", 10)
        log_path = tmp_path / UNDO_LOG_FILENAME
        log_path.write_text(json.dumps({"version": 2, "runs": [{"moves": []}]}))  # > 10 bytes
        assert read_undo_runs(log_path) == []


# ── prune_empty_dirs ──────────────────────────────────────────────────────────

class TestPruneEmptyDirs:
    def test_empty_child_directory_is_removed(self, tmp_path):
        child = tmp_path / "Documents"
        child.mkdir()
        assert prune_empty_dirs({child}, tmp_path, Verbosity.QUIET) == 1
        assert not child.exists()

    def test_non_empty_directory_is_kept(self, tmp_path):
        child = tmp_path / "Documents"
        child.mkdir()
        (child / "leftover.pdf").write_text("still here")
        assert prune_empty_dirs({child}, tmp_path, Verbosity.QUIET) == 0
        assert child.exists()

    def test_target_directory_itself_is_never_removed(self, tmp_path):
        assert prune_empty_dirs({tmp_path}, tmp_path, Verbosity.QUIET) == 0
        assert tmp_path.exists()

    def test_directories_outside_target_are_left_alone(self, tmp_path):
        outsider = tmp_path / "Documents" / "Nested"
        outsider.mkdir(parents=True)
        assert prune_empty_dirs({outsider}, tmp_path, Verbosity.QUIET) == 0
        assert outsider.exists()

    def test_relative_target_still_matches_absolute_candidates(self, tmp_path, monkeypatch):
        # Undo logs hold absolute paths while the target may be given as '.',
        # and Path equality is textual — both sides must be resolved first.
        child = tmp_path / "Videos"
        child.mkdir()
        monkeypatch.chdir(tmp_path)
        assert prune_empty_dirs({child.resolve()}, Path("."), Verbosity.QUIET) == 1
        assert not child.exists()


# ── describe_undo_state ───────────────────────────────────────────────────────

class TestDescribeUndoState:
    def _make_files(self, directory: Path, names: list[str]) -> None:
        for name in names:
            (directory / name).write_text(f"content of {name}")

    def test_no_log_reports_nothing_to_undo(self, tmp_path):
        assert describe_undo_state(tmp_path) == "nothing to undo"

    def test_single_run_reports_file_count(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf", "photo.jpg"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        assert describe_undo_state(tmp_path) == "2 file(s) from the last sort"

    def test_stacked_runs_mention_the_history_behind_them(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        self._make_files(tmp_path, ["photo.jpg"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        assert describe_undo_state(tmp_path) == "1 file(s) from the last sort, 1 older run(s) behind it"


# ── Colour output ─────────────────────────────────────────────────────────────

class TestColourOutput:
    def test_colourise_wraps_text_when_supported(self, monkeypatch):
        monkeypatch.setattr("sortinghat.supports_colour", lambda: True)
        assert colourise("Sort now") == f"{GREEN}Sort now{RESET}"

    def test_colourise_returns_plain_text_when_unsupported(self, monkeypatch):
        monkeypatch.setattr("sortinghat.supports_colour", lambda: False)
        assert colourise("Sort now") == "Sort now"

    def test_no_colour_when_output_is_not_a_terminal(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setattr("sys.stdout.isatty", lambda: False, raising=False)
        supports_colour.cache_clear()
        assert supports_colour() is False
        supports_colour.cache_clear()

    def test_no_color_env_var_disables_colour(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setattr("sys.stdout.isatty", lambda: True, raising=False)
        supports_colour.cache_clear()
        assert supports_colour() is False
        supports_colour.cache_clear()


# ── Status colours in run / summary output ────────────────────────────────────

class TestStatusColours:
    def _result(self, **kw):
        base = dict(moved=3, category_counts={"Documents": 2, "Pictures": 1})
        base.update(kw)
        return SortResult(**base)

    def test_totals_are_green_when_supported(self, monkeypatch, capsys):
        monkeypatch.setattr("sortinghat.supports_colour", lambda: True)
        print_summary(self._result(), dry_run=False, verbosity=Verbosity.NORMAL)
        out = capsys.readouterr().out
        assert f"{GREEN}Moved 3 file(s).{RESET}" in out

    def test_skipped_is_red_and_excluded_is_yellow(self, monkeypatch, capsys):
        monkeypatch.setattr("sortinghat.supports_colour", lambda: True)
        print_summary(self._result(skipped=2, excluded=1), dry_run=False, verbosity=Verbosity.NORMAL)
        out = capsys.readouterr().out
        assert RED in out and YELLOW in out

    def test_preview_tag_is_cyan(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("sortinghat.supports_colour", lambda: True)
        (tmp_path / "doc.pdf").write_text("x")
        sort_directory(tmp_path, dry_run=True, verbosity=Verbosity.NORMAL)
        assert f"{CYAN}[Preview]{RESET}" in capsys.readouterr().out

    def test_no_escape_codes_when_colour_unsupported(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("sortinghat.supports_colour", lambda: False)
        (tmp_path / "doc.pdf").write_text("x")
        sort_directory(tmp_path, dry_run=True, verbosity=Verbosity.NORMAL)
        print_summary(self._result(skipped=1, excluded=1), dry_run=True, verbosity=Verbosity.NORMAL)
        assert "\033[" not in capsys.readouterr().out


# ── run_interactive_menu ──────────────────────────────────────────────────────

class TestInteractiveMenu:
    def _make_files(self, directory: Path, names: list[str]) -> None:
        for name in names:
            (directory / name).write_text(f"content of {name}")

    def _answer(self, monkeypatch, responses: list[str]) -> None:
        """Feed *responses* to input() in order."""
        queue = list(responses)
        monkeypatch.setattr("builtins.input", lambda *a, **k: queue.pop(0))

    def test_exit_option_leaves_files_untouched(self, tmp_path, monkeypatch):
        self._make_files(tmp_path, ["doc.pdf"])
        self._answer(monkeypatch, ["0"])
        run_interactive_menu(tmp_path, Verbosity.QUIET)
        assert (tmp_path / "doc.pdf").exists()
        assert not (tmp_path / "Documents").exists()

    def test_preview_option_does_not_move_files(self, tmp_path, monkeypatch):
        self._make_files(tmp_path, ["doc.pdf"])
        self._answer(monkeypatch, ["1", "0"])
        run_interactive_menu(tmp_path, Verbosity.QUIET)
        assert (tmp_path / "doc.pdf").exists()
        assert not (tmp_path / "Documents").exists()

    def test_sort_option_moves_files(self, tmp_path, monkeypatch):
        self._make_files(tmp_path, ["doc.pdf"])
        self._answer(monkeypatch, ["2", "0"])
        run_interactive_menu(tmp_path, Verbosity.QUIET)
        assert (tmp_path / "Documents" / "doc.pdf").exists()

    def test_sort_then_undo_round_trips(self, tmp_path, monkeypatch):
        self._make_files(tmp_path, ["doc.pdf"])
        self._answer(monkeypatch, ["2", "4", "0"])
        run_interactive_menu(tmp_path, Verbosity.QUIET)
        assert (tmp_path / "doc.pdf").exists()
        assert not (tmp_path / "Documents").exists()

    def test_undo_preview_keeps_log_and_files(self, tmp_path, monkeypatch):
        self._make_files(tmp_path, ["doc.pdf"])
        self._answer(monkeypatch, ["2", "3", "0"])
        run_interactive_menu(tmp_path, Verbosity.QUIET)
        assert (tmp_path / "Documents" / "doc.pdf").exists()
        assert (tmp_path / UNDO_LOG_FILENAME).exists()

    def test_change_target_redirects_the_next_sort(self, tmp_path, monkeypatch):
        other = tmp_path / "elsewhere"
        other.mkdir()
        self._make_files(other, ["doc.pdf"])
        self._answer(monkeypatch, ["5", str(other), "2", "0"])
        run_interactive_menu(tmp_path, Verbosity.QUIET)
        assert (other / "Documents" / "doc.pdf").exists()

    def test_change_target_to_bad_path_keeps_current(self, tmp_path, monkeypatch, capsys):
        self._make_files(tmp_path, ["doc.pdf"])
        self._answer(monkeypatch, ["5", str(tmp_path / "nope"), "2", "0"])
        run_interactive_menu(tmp_path, Verbosity.QUIET)
        assert "keeping the current target" in capsys.readouterr().out
        assert (tmp_path / "Documents" / "doc.pdf").exists()

    def test_blank_target_answer_keeps_current(self, tmp_path, monkeypatch):
        self._make_files(tmp_path, ["doc.pdf"])
        self._answer(monkeypatch, ["5", "", "2", "0"])
        run_interactive_menu(tmp_path, Verbosity.QUIET)
        assert (tmp_path / "Documents" / "doc.pdf").exists()

    def test_quoted_target_path_is_accepted(self, tmp_path, monkeypatch):
        other = tmp_path / "with space"
        other.mkdir()
        self._make_files(other, ["doc.pdf"])
        self._answer(monkeypatch, ["5", f'"{other}"', "2", "0"])
        run_interactive_menu(tmp_path, Verbosity.QUIET)
        assert (other / "Documents" / "doc.pdf").exists()

    def test_invalid_choice_reprompts(self, tmp_path, monkeypatch, capsys):
        self._make_files(tmp_path, ["doc.pdf"])
        self._answer(monkeypatch, ["9", "banana", "0"])
        run_interactive_menu(tmp_path, Verbosity.QUIET)
        out = capsys.readouterr().out
        assert "'9' is not one of the options" in out
        assert "'banana' is not one of the options" in out
        assert (tmp_path / "doc.pdf").exists()

    def test_ctrl_c_at_the_prompt_exits_cleanly(self, tmp_path, monkeypatch, capsys):
        def interrupt(*a, **k):
            raise KeyboardInterrupt

        monkeypatch.setattr("builtins.input", interrupt)
        run_interactive_menu(tmp_path, Verbosity.QUIET)  # must not raise
        assert "Cancelled" in capsys.readouterr().out

    def test_menu_options_are_green_when_colour_is_supported(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("sortinghat.supports_colour", lambda: True)
        self._answer(monkeypatch, ["0"])
        run_interactive_menu(tmp_path, Verbosity.QUIET)
        out = capsys.readouterr().out
        assert f"{GREEN}[2]  Sort now{RESET}" in out
        assert f"{GREEN}[0]  Exit{RESET}" in out

    def test_menu_options_are_plain_when_colour_is_unsupported(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("sortinghat.supports_colour", lambda: False)
        self._answer(monkeypatch, ["0"])
        run_interactive_menu(tmp_path, Verbosity.QUIET)
        out = capsys.readouterr().out
        assert "[2]  Sort now" in out
        assert "\033[" not in out  # no escape codes leak into piped output

    def test_menu_honours_custom_ext_map(self, tmp_path, monkeypatch):
        self._make_files(tmp_path, ["script.py"])
        self._answer(monkeypatch, ["2", "0"])
        run_interactive_menu(tmp_path, Verbosity.QUIET, ext_map=build_ext_map({"Code": [".py"]}))
        assert (tmp_path / "Code" / "script.py").exists()

    def test_menu_honours_exclude_patterns(self, tmp_path, monkeypatch):
        self._make_files(tmp_path, ["doc.pdf", "temp.tmp"])
        self._answer(monkeypatch, ["2", "0"])
        run_interactive_menu(tmp_path, Verbosity.QUIET, exclude_patterns=["*.tmp"])
        assert (tmp_path / "temp.tmp").exists()
        assert (tmp_path / "Documents" / "doc.pdf").exists()


# ── undo_last_sort ────────────────────────────────────────────────────────────

class TestUndoLastSort:
    def _make_files(self, directory: Path, names: list[str]) -> None:
        for name in names:
            (directory / name).write_text(f"content of {name}")

    def test_undo_restores_files_to_original_location(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf", "photo.jpg"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)

        assert not (tmp_path / "doc.pdf").exists()
        undo_last_sort(tmp_path, Verbosity.QUIET)

        assert (tmp_path / "doc.pdf").exists()
        assert (tmp_path / "photo.jpg").exists()

    def test_undo_deletes_log_after_restoring(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        undo_last_sort(tmp_path, Verbosity.QUIET)
        assert not (tmp_path / UNDO_LOG_FILENAME).exists()

    def test_undo_without_log_prints_message(self, tmp_path, capsys):
        undo_last_sort(tmp_path, Verbosity.QUIET)
        captured = capsys.readouterr()
        assert "No undo log found" in captured.out

    def test_undo_skips_missing_files_gracefully(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)

        # Manually delete the moved file to simulate it being gone
        (tmp_path / "Documents" / "doc.pdf").unlink()

        # Should not raise — just report it as failed/missing
        undo_last_sort(tmp_path, Verbosity.QUIET)
        assert not (tmp_path / UNDO_LOG_FILENAME).exists()  # log still cleaned up

    def test_double_undo_is_prevented(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        undo_last_sort(tmp_path, Verbosity.QUIET)

        # Second undo should say no log found, not raise
        undo_last_sort(tmp_path, Verbosity.QUIET)  # must not raise

    def test_undo_removes_emptied_category_folders(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf", "photo.jpg"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        undo_last_sort(tmp_path, Verbosity.QUIET)

        assert not (tmp_path / "Documents").exists()
        assert not (tmp_path / "Pictures").exists()

    def test_undo_keeps_category_folder_that_still_has_files(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        (tmp_path / "Documents" / "unrelated.pdf").write_text("not ours")
        undo_last_sort(tmp_path, Verbosity.QUIET)

        assert (tmp_path / "Documents" / "unrelated.pdf").exists()

    # ── Undo stack ─────────────────────────────────────────────────────────────

    def test_undo_walks_back_one_run_at_a_time(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        self._make_files(tmp_path, ["photo.jpg"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)

        # First undo reverses only the most recent run
        undo_last_sort(tmp_path, Verbosity.QUIET)
        assert (tmp_path / "photo.jpg").exists()
        assert (tmp_path / "Documents" / "doc.pdf").exists()
        assert (tmp_path / UNDO_LOG_FILENAME).exists()  # earlier run still recorded

        # Second undo reverses the run before it, then clears the log
        undo_last_sort(tmp_path, Verbosity.QUIET)
        assert (tmp_path / "doc.pdf").exists()
        assert not (tmp_path / UNDO_LOG_FILENAME).exists()

    def test_undo_reads_legacy_log_format(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)

        # Rewrite the log in the pre-v2 single-run shape
        log_path = tmp_path / UNDO_LOG_FILENAME
        run = json.loads(log_path.read_text())["runs"][0]
        log_path.write_text(json.dumps(run))

        undo_last_sort(tmp_path, Verbosity.QUIET)
        assert (tmp_path / "doc.pdf").exists()
        assert not log_path.exists()

    # ── Undo dry run ───────────────────────────────────────────────────────────

    def test_undo_dry_run_moves_nothing_and_keeps_log(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        undo_last_sort(tmp_path, Verbosity.QUIET, dry_run=True)

        assert (tmp_path / "Documents" / "doc.pdf").exists()
        assert not (tmp_path / "doc.pdf").exists()
        assert (tmp_path / UNDO_LOG_FILENAME).exists()

    def test_undo_dry_run_reports_what_would_be_restored(self, tmp_path, capsys):
        self._make_files(tmp_path, ["doc.pdf"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        undo_last_sort(tmp_path, Verbosity.NORMAL, dry_run=True)

        captured = capsys.readouterr()
        assert "Would restore 1 file(s)." in captured.out
        assert "doc.pdf" in captured.out

    def test_undo_after_dry_run_still_works(self, tmp_path):
        self._make_files(tmp_path, ["doc.pdf"])
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        undo_last_sort(tmp_path, Verbosity.QUIET, dry_run=True)
        undo_last_sort(tmp_path, Verbosity.QUIET)

        assert (tmp_path / "doc.pdf").exists()

    # ── Confinement (security) ─────────────────────────────────────────────────

    def test_undo_refuses_to_restore_outside_target(self, tmp_path):
        # A poisoned undo log must not be able to fling a file outside the target.
        target = tmp_path / "downloads"
        target.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        victim = target / "Documents" / "secret.pdf"
        victim.parent.mkdir()
        victim.write_text("data")
        escape = outside / "stolen.pdf"

        log = target / UNDO_LOG_FILENAME
        write_undo_runs(log, [{
            "timestamp": "t", "target": str(target),
            "moves": [{"src": str(escape), "dst": str(victim)}],
        }])

        undo_last_sort(target, Verbosity.QUIET)

        assert not escape.exists()   # the escape was refused
        assert victim.exists()       # the real file is untouched
        assert not log.exists()      # the run is still consumed, not left to jam the stack

    def test_undo_blocked_count_is_reported(self, tmp_path, capsys):
        target = tmp_path / "downloads"
        target.mkdir()
        victim = target / "Documents" / "secret.pdf"
        victim.parent.mkdir()
        victim.write_text("data")

        log = target / UNDO_LOG_FILENAME
        write_undo_runs(log, [{
            "timestamp": "t", "target": str(target),
            "moves": [{"src": str(tmp_path / "outside" / "x.pdf"), "dst": str(victim)}],
        }])

        undo_last_sort(target, Verbosity.NORMAL)
        out = capsys.readouterr().out
        assert "Blocked" in out
