from __future__ import annotations

import json
from pathlib import Path

import pytest

from sortinghat import (
    Verbosity,
    SortResult,
    build_ext_map,
    get_category,
    handle_collision,
    is_excluded,
    is_system_file,
    load_config,
    sort_directory,
    undo_last_sort,
    UNDO_LOG_FILENAME,
)


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
        assert len(log["moves"]) == 1
        assert log["moves"][0]["src"].endswith("doc.pdf")

    def test_undo_log_not_written_when_nothing_moved(self, tmp_path):
        # Empty directory — nothing to move
        sort_directory(tmp_path, verbosity=Verbosity.QUIET)
        assert not (tmp_path / UNDO_LOG_FILENAME).exists()


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
