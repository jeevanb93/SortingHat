from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import sys
from collections import defaultdict
from functools import lru_cache
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

# ── Banner ────────────────────────────────────────────────────────────────────

BANNER = r"""
 ____             _   _             _   _       _
/ ___|  ___  _ __| |_(_)_ __   __ _| | | | __ _| |_
\___ \ / _ \| '__| __| | '_ \ / _` | |_| |/ _` | __|
 ___) | (_) | |  | |_| | | | | (_| |  _  | (_| | |_
|____/ \___/|_|   \__|_|_| |_|\__, |_| |_|\__,_|\__|
                               |___/
"""

# ── Extension map ─────────────────────────────────────────────────────────────

EXTENSION_MAPPING: dict[str, list[str]] = {
    "Compressed": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".zst"],
    "Documents":  [".pdf", ".docx", ".doc", ".txt", ".xlsx", ".xls", ".pptx", ".ppt",
                   ".csv", ".epub", ".odt", ".rtf", ".md", ".json", ".xml", ".pages"],
    "Installers": [".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".appimage"],
    "Music":      [".mp3", ".wav", ".aac", ".flac", ".ogg", ".opus", ".m4a", ".wma", ".aiff"],
    "Pictures":   [".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp", ".heic",
                   ".tiff", ".tif", ".webp", ".ico", ".raw", ".cr2", ".nef"],
    "Torrents":   [".torrent"],
    "Videos":     [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".flv"],
}

SYSTEM_FILES: set[str] = {"desktop.ini", "thumbs.db"}
UNDO_LOG_FILENAME = ".sortinghat_undo.json"
UNDO_LOG_VERSION = 2

# A sane ceiling on the undo log so a crafted or corrupt file can't force an
# unbounded read into memory. A real log is a few hundred bytes per move.
MAX_UNDO_LOG_BYTES = 50 * 1024 * 1024

# Characters that must never appear in a category name: path separators, the
# Windows drive colon, and the reserved filename characters. A category becomes
# a sub-folder, so these are exactly what would let it escape the target folder.
_INVALID_CATEGORY_CHARS = set('/\\:*?"<>|')


# ── Enums & data classes ──────────────────────────────────────────────────────

class Verbosity(Enum):
    QUIET   = 0  # summary only
    NORMAL  = 1  # per-file moves (default)
    VERBOSE = 2  # per-file moves + system/excluded details


@dataclass
class SortResult:
    """Accumulates counts and a per-category breakdown from a sort run."""
    moved:           int = 0
    skipped:         int = 0
    system_ignored:  int = 0
    excluded:        int = 0
    category_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class UndoResult:
    """Outcome of an undo run, so presentation can render the summary from data."""
    found:     bool = True   # False when there was no undo log to act on
    restored:  int = 0
    failed:    int = 0
    blocked:   int = 0
    cleaned:   int = 0
    remaining: int = 0       # earlier runs still on the stack
    count:     int = 0       # entries in the run being undone
    timestamp: str = "unknown"
    dry_run:   bool = False


# ── Path safety helpers ───────────────────────────────────────────────────────

def is_within(child: Path, parent: Path) -> bool:
    """
    True if *child* resolves to *parent* or somewhere beneath it.
    Used to keep undo restores and category folders confined to the target, so a
    crafted undo log or config can't relocate files outside it. ``is_relative_to``
    only landed in 3.9, so this uses ``relative_to`` for our 3.8 floor.
    """
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def sanitize_category(name: str) -> str:
    """
    Return *name* unchanged if it is safe to use as a sub-folder name, else raise
    ``ValueError``. Rejects empty names, ``..`` traversal, and any path separator
    or drive/reserved character — all of which could push files outside the
    target folder (e.g. ``"C:/Windows"`` or ``"../../elsewhere"``).
    """
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("category name may not be empty")
    if cleaned in {".", ".."} or ".." in cleaned:
        raise ValueError(f"category name '{name}' may not contain '..'")
    if any(char in _INVALID_CATEGORY_CHARS for char in cleaned):
        raise ValueError(f"category name '{name}' contains an invalid path character")
    return cleaned


# ── Config & extension-map helpers ────────────────────────────────────────────

def load_config(config_path: Path) -> dict[str, list[str]]:
    """Parse a JSON config file and return its validated category -> extensions mapping."""
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"  Error: Config file '{config_path}' not found.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"  Error: Invalid JSON in config file: {e}")
        sys.exit(1)
    if not isinstance(raw, dict):
        print("  Error: Config must be a JSON object mapping category names to extension lists.")
        sys.exit(1)

    for category, extensions in raw.items():
        try:
            sanitize_category(category)
        except ValueError as e:
            print(f"  Error: {e}.")
            sys.exit(1)
        # A bare string is iterable, so without this check "py" would silently
        # become the extensions 'p' and 'y'. Require an explicit list of strings.
        if not isinstance(extensions, list) or not all(isinstance(e, str) for e in extensions):
            print(f"  Error: extensions for category '{category}' must be a list of strings.")
            sys.exit(1)
        for ext in extensions:
            if not ext.startswith(".") or len(ext) < 2:
                print(f"  Error: extension '{ext}' in category '{category}' must start with a dot, e.g. '.py'.")
                sys.exit(1)
    return raw


def build_ext_map(extra: dict[str, list[str]] | None = None) -> dict[str, str]:
    """
    Build the extension -> category lookup dict.
    If *extra* is provided (from ``--config``), its entries are merged in:
    new categories are added; existing categories have their extensions extended.
    """
    merged: dict[str, list[str]] = {cat: list(exts) for cat, exts in EXTENSION_MAPPING.items()}
    if extra:
        for cat, exts in extra.items():
            sanitize_category(cat)  # guards callers that bypass load_config (e.g. the GUI)
            normalised = [e.lower() for e in exts]
            if cat in merged:
                merged[cat] = list(set(merged[cat]) | set(normalised))
            else:
                merged[cat] = normalised
    return {ext: cat for cat, exts in merged.items() for ext in exts}


# ── Core helpers ──────────────────────────────────────────────────────────────

def get_category(extension: str, ext_map: dict[str, str]) -> str:
    """Return the category name for a given file extension."""
    return ext_map.get(extension.lower(), "Misc")


def is_system_file(file_path: Path) -> bool:
    """Return True for dotfiles and known OS system files."""
    return file_path.name.startswith(".") or file_path.name.lower() in SYSTEM_FILES


def is_excluded(file_path: Path, patterns: list[str]) -> bool:
    """Return True if the filename matches any user-supplied glob pattern."""
    return any(fnmatch.fnmatch(file_path.name, pattern) for pattern in patterns)


def handle_collision(dest_file_path: Path, occupied: set[Path] | None = None) -> Path:
    """
    Return a safe destination path that avoids:
      - Real files already on the filesystem.
      - Paths already claimed this session (``occupied``) for dry-run accuracy.
    """
    if occupied is None:
        occupied = set()
    # os.path.lexists (not .exists) so a *broken* symlink sitting at the
    # destination still counts as occupied — otherwise shutil.move could
    # silently clobber it on POSIX, breaking the never-overwrite guarantee.
    if not os.path.lexists(dest_file_path) and dest_file_path not in occupied:
        return dest_file_path
    stem, suffix, directory = dest_file_path.stem, dest_file_path.suffix, dest_file_path.parent
    counter = 1
    while True:
        new_path = directory / f"{stem} ({counter}){suffix}"
        if not os.path.lexists(new_path) and new_path not in occupied:
            return new_path
        counter += 1


# ── Undo log helpers ──────────────────────────────────────────────────────────

def read_undo_runs(log_path: Path) -> list[dict]:
    """
    Return the list of recorded runs, oldest first.
    Logs written by older versions held a single run at the top level; those are
    read back as a one-element list so an upgrade never strands an existing undo.
    """
    if not log_path.exists():
        return []
    if log_path.stat().st_size > MAX_UNDO_LOG_BYTES:
        print(f"  Warning: undo log '{log_path}' is unexpectedly large and will be ignored.\n")
        return []
    try:
        data = json.loads(log_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"  Warning: undo log '{log_path}' is corrupt and will be ignored.\n")
        return []
    if isinstance(data, dict) and "runs" in data:
        return list(data["runs"])
    if isinstance(data, dict) and "moves" in data:  # legacy single-run format
        return [data]
    return []


def write_undo_runs(log_path: Path, runs: list[dict]) -> None:
    """Persist *runs* (oldest first), or remove the log entirely when empty."""
    if not runs:
        log_path.unlink(missing_ok=True)
        return
    log_path.write_text(
        json.dumps({"version": UNDO_LOG_VERSION, "runs": runs}, indent=2),
        encoding="utf-8",
    )


def prune_empty_dirs(candidates: set[Path], target_dir: Path, verbosity: Verbosity) -> int:
    """
    Remove now-empty category folders left behind by an undo.
    Only touches directories directly inside *target_dir*, and never the target
    itself, so a stray empty folder elsewhere is never collateral damage.
    Paths are resolved before comparison — undo logs hold absolute paths, while
    *target_dir* may be relative (``sortinghat .``), and Path equality is textual.
    """
    removed = 0
    target = target_dir.resolve()
    for directory in sorted(candidates):
        directory = directory.resolve()
        if directory == target or directory.parent != target:
            continue
        if not directory.is_dir() or any(directory.iterdir()):
            continue
        try:
            directory.rmdir()
            removed += 1
            if verbosity == Verbosity.VERBOSE:
                print(f"  [Cleaned]  Removed empty folder '{directory.name}'\n")
        except OSError:
            pass  # in use or permission denied — harmless to leave behind
    return removed


# ── Sorting logic ─────────────────────────────────────────────────────────────

def sort_directory(
    target_dir: Path,
    dry_run: bool = False,
    exclude_patterns: list[str] | None = None,
    verbosity: Verbosity = Verbosity.NORMAL,
    ext_map: dict[str, str] | None = None,
    reporter: Reporter | None = None,
) -> SortResult:
    """
    Scan *target_dir* and sort every file into category sub-folders.
    Returns a :class:`SortResult` with counts and a per-category breakdown.
    On a live run, writes an undo log to *target_dir* so the sort can be reversed.

    Progress and per-file activity are emitted to *reporter*; when none is given a
    :class:`ConsoleReporter` at *verbosity* is used, preserving the terminal output.
    """
    if exclude_patterns is None:
        exclude_patterns = []
    if ext_map is None:
        ext_map = build_ext_map()
    if reporter is None:
        reporter = ConsoleReporter(verbosity)

    result: SortResult = SortResult()
    category_counts: dict[str, int] = defaultdict(int)
    occupied: set[Path] = set()
    undo_log: list[dict[str, str]] = []

    entries = sorted(target_dir.iterdir())
    total = len(entries)
    for index, file_path in enumerate(entries, start=1):
        reporter.progress(index, total)

        # Skip symlinks before is_file(), which would follow the link and let a
        # link to a file elsewhere be categorised (and moved) as if it were local.
        if file_path.is_symlink():
            result.system_ignored += 1
            reporter.ignored(file_path.name, "symlink")
            continue

        if not file_path.is_file():
            continue

        if is_system_file(file_path):
            result.system_ignored += 1
            reporter.ignored(file_path.name, "system")
            continue

        if exclude_patterns and is_excluded(file_path, exclude_patterns):
            result.excluded += 1
            reporter.excluded(file_path.name)
            continue

        category   = get_category(file_path.suffix, ext_map)
        dest_folder = target_dir / category
        final_dest = handle_collision(dest_folder / file_path.name, occupied)
        renamed    = final_dest.name != file_path.name

        if dry_run:
            reporter.previewed(file_path.name, category, final_dest.name, renamed)
            occupied.add(final_dest)
            result.moved += 1
            category_counts[category] += 1
        else:
            dest_folder.mkdir(parents=True, exist_ok=True)
            reporter.moved(file_path.name, category, final_dest.name, renamed)
            try:
                shutil.move(str(file_path), str(final_dest))
                undo_log.append({"src": str(file_path), "dst": str(final_dest)})
                result.moved += 1
                category_counts[category] += 1
            except PermissionError:
                reporter.skipped(file_path.name, "Permission denied - file may be in use.")
                result.skipped += 1
            except OSError as e:
                reporter.skipped(file_path.name, f"OS error: {e}")
                result.skipped += 1

    result.category_counts = dict(category_counts)

    # Append this run to the undo log on live runs
    if not dry_run and undo_log:
        log_path = target_dir / UNDO_LOG_FILENAME
        runs = read_undo_runs(log_path)
        runs.append({"timestamp": datetime.now(timezone.utc).isoformat(),
                     "target": str(target_dir), "moves": undo_log})
        write_undo_runs(log_path, runs)
        reporter.note(f"Undo log written to: {log_path} ({len(runs)} run(s) recorded)")

    return result


# ── Undo logic ────────────────────────────────────────────────────────────────

def undo_last_sort(
    target_dir: Path,
    verbosity: Verbosity = Verbosity.NORMAL,
    dry_run: bool = False,
    reporter: Reporter | None = None,
) -> UndoResult:
    """
    Reverse the most recent sort run recorded in *target_dir*.
    Runs are stacked, so repeated calls walk back through the history one sort at
    a time. With *dry_run* the log is left untouched and nothing is moved.

    Returns an :class:`UndoResult`; activity is emitted to *reporter* (a
    :class:`ConsoleReporter` at *verbosity* by default).
    """
    if reporter is None:
        reporter = ConsoleReporter(verbosity)

    log_path = target_dir / UNDO_LOG_FILENAME
    runs = read_undo_runs(log_path)
    if not runs:
        reporter.no_undo_log(target_dir)
        return UndoResult(found=False, dry_run=dry_run)

    run       = runs[-1]
    timestamp = run.get("timestamp", "unknown")
    remaining = len(runs) - 1

    # Confine every restore to the target folder. The undo log is a plain file in
    # a folder that fills with untrusted downloads, so a crafted entry could
    # otherwise move an arbitrary file to an arbitrary location. Entries whose
    # source or destination escape the target are refused, not executed.
    moves, blocked = [], 0
    for entry in run.get("moves", []):
        src, dst = Path(entry.get("src", "")), Path(entry.get("dst", ""))
        if not (is_within(src, target_dir) and is_within(dst, target_dir)):
            blocked += 1
            reporter.blocked(dst.name or str(entry))
            continue
        moves.append(entry)

    reporter.undo_started(len(moves), timestamp, dry_run)

    undone, failed = 0, 0
    occupied: set[Path] = set()
    touched_dirs: set[Path] = set()

    for entry in reversed(moves):
        src, dst = Path(entry["src"]), Path(entry["dst"])
        if not dst.exists():
            reporter.missing(dst.name)
            failed += 1
            continue
        final_src = handle_collision(src, occupied)
        reporter.restored(dst.name, final_src, dry_run)
        if dry_run:
            occupied.add(final_src)
            undone += 1
            continue
        try:
            shutil.move(str(dst), str(final_src))
            touched_dirs.add(dst.parent)
            undone += 1
        except (PermissionError, OSError) as e:
            reporter.failed(dst.name, str(e))
            failed += 1

    cleaned = 0
    if not dry_run:
        cleaned = prune_empty_dirs(touched_dirs, target_dir, verbosity)
        runs.pop()  # prevent double-undo of the same run
        write_undo_runs(log_path, runs)

    result = UndoResult(found=True, restored=undone, failed=failed, blocked=blocked,
                        cleaned=cleaned, remaining=remaining, count=len(moves),
                        timestamp=timestamp, dry_run=dry_run)
    reporter.undo_summary(result)
    return result


# ── Output helpers ────────────────────────────────────────────────────────────

def print_summary(result: SortResult, dry_run: bool, verbosity: Verbosity) -> None:
    """Render the final summary table to stdout."""
    print("-" * 60)
    action = "Would move" if dry_run else "Moved"

    if result.category_counts:
        BAR_WIDTH = 20
        max_count = max(result.category_counts.values())
        total     = sum(result.category_counts.values())

        print(f"\n  {colourise(f'{action} {total} file(s).', GREEN)}\n")
        print(f"  {'Category':<14}  {'':20}  Count")
        print(f"  {'-'*14}  {'-'*20}  -----")
        for cat, count in sorted(result.category_counts.items()):
            filled = round((count / max_count) * BAR_WIDTH)
            bar    = "#" * filled + "-" * (BAR_WIDTH - filled)
            print(f"  {cat:<14}  [{bar}]  {count}")
        print(f"  {'-'*14}  {' '*20}  -----")
        print(f"  {'Total':<14}  {' '*20}  {total}")
    else:
        print(f"\n  {colourise(f'{action} 0 file(s).', GREEN)}")

    if result.skipped:
        print(f"\n  {colourise(f'Skipped  : {result.skipped} file(s) due to errors.', RED)}")
    if result.excluded:
        print(f"  {colourise(f'Excluded : {result.excluded} file(s) matched --exclude pattern(s).', YELLOW)}")
    if result.system_ignored and verbosity != Verbosity.QUIET:
        print(f"  Ignored  : {result.system_ignored} system/hidden file(s).")
    print()


def _wait_for_exit() -> None:
    """Pause before the window closes — only active when running as a compiled .exe."""
    if getattr(sys, "frozen", False):
        try:
            input("\nPress Enter to exit...")
        except (EOFError, KeyboardInterrupt):
            pass  # piped or cancelled input — just close


# ── Colour output ─────────────────────────────────────────────────────────────

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"


def _enable_windows_ansi() -> bool:
    """
    Ask the Windows console to interpret ANSI escapes rather than print them.
    Windows Terminal does this already; older conhost windows — the ones a
    double-clicked .exe often lands in — need to be asked.
    """
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # 0x0004 = ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False  # no console, no ctypes, or an OS that refuses — fall back to plain text


@lru_cache(maxsize=1)
def supports_colour() -> bool:
    """
    True when it is safe to emit ANSI colour. Checked once and cached, since the
    answer cannot change mid-run.
    """
    if os.environ.get("NO_COLOR"):        # https://no-color.org
        return False
    if not sys.stdout.isatty():           # piped or redirected — keep the text clean
        return False
    return _enable_windows_ansi()


def colourise(text: str, colour: str = GREEN) -> str:
    """Wrap *text* in an ANSI colour, or return it untouched when colour is unavailable."""
    return f"{colour}{text}{RESET}" if supports_colour() else text


# ── Reporting seam ────────────────────────────────────────────────────────────
#
# The engine (sort_directory / undo_last_sort) never prints directly. It emits
# events to a Reporter, and each presentation layer supplies its own: the CLI a
# ConsoleReporter that writes coloured text to stdout, the GUI a reporter that
# marshals the same events onto its widgets. Every method defaults to a no-op so
# a reporter only overrides what it cares about (the console ignores `progress`;
# the GUI uses it for a progress bar). This one seam is what lets both front-ends
# reuse the real engine instead of duplicating it or scraping stdout.

class Reporter:
    """Sink for engine events. Presentation layers subclass and override selectively."""

    # ── sort events ──
    def moved(self, name: str, category: str, dest_name: str, renamed: bool) -> None: ...
    def previewed(self, name: str, category: str, dest_name: str, renamed: bool) -> None: ...
    def skipped(self, name: str, reason: str) -> None: ...
    def excluded(self, name: str) -> None: ...
    def ignored(self, name: str, kind: str) -> None: ...          # kind: "system" | "symlink"

    # ── undo events ──
    def undo_started(self, count: int, timestamp: str, dry_run: bool) -> None: ...
    def restored(self, name: str, dest: Path, dry_run: bool) -> None: ...
    def missing(self, name: str) -> None: ...
    def blocked(self, name: str) -> None: ...
    def failed(self, name: str, error: str) -> None: ...
    def no_undo_log(self, target_dir: Path) -> None: ...
    def undo_summary(self, result: UndoResult) -> None: ...

    # ── shared ──
    def progress(self, done: int, total: int) -> None: ...
    def note(self, message: str) -> None: ...                     # verbose-only asides


class ConsoleReporter(Reporter):
    """Reporter that reproduces SortingHat's coloured terminal output, gated by verbosity."""

    def __init__(self, verbosity: Verbosity = Verbosity.NORMAL) -> None:
        self.verbosity = verbosity

    @staticmethod
    def _rename_note(renamed: bool) -> str:
        return " (renamed to avoid collision)" if renamed else ""

    def moved(self, name, category, dest_name, renamed):
        if self.verbosity != Verbosity.QUIET:
            print(f"  Moving  {name}")
            print(f"       -> {category}/{dest_name}{self._rename_note(renamed)}\n")

    def previewed(self, name, category, dest_name, renamed):
        if self.verbosity != Verbosity.QUIET:
            print(f"  {colourise('[Preview]', CYAN)}  {name}")
            print(f"             -> {category}/{dest_name}{self._rename_note(renamed)}\n")

    def skipped(self, name, reason):
        print(f"  {colourise('[SKIPPED]', RED)} {reason}\n")

    def excluded(self, name):
        if self.verbosity != Verbosity.QUIET:
            print(f"  {colourise('[Excluded]', YELLOW)} {name}\n")

    def ignored(self, name, kind):
        if self.verbosity == Verbosity.VERBOSE:
            if kind == "symlink":
                print(f"  [Link]     {name} (symlink skipped)\n")
            else:
                print(f"  [System]   {name}\n")

    def undo_started(self, count, timestamp, dry_run):
        print(f"  {'Would undo' if dry_run else 'Undoing'} {count} move(s) from {timestamp}...\n")
        print("-" * 60)
        print()

    def restored(self, name, dest, dry_run):
        if self.verbosity != Verbosity.QUIET:
            label = colourise("[Preview]  Would restore", CYAN) if dry_run else "Restoring "
            print(f"  {label} {name}")
            print(f"         ->  {dest}\n")

    def missing(self, name):
        if self.verbosity != Verbosity.QUIET:
            print(f"  {colourise('[Missing]', YELLOW)}  '{name}' no longer exists - skipping.\n")

    def blocked(self, name):
        if self.verbosity != Verbosity.QUIET:
            print(f"  {colourise('[Blocked]', RED)}  Refusing to restore outside the target folder: '{name}'\n")

    def failed(self, name, error):
        print(f"  {colourise('[FAILED]', RED)}   Could not restore '{name}': {error}\n")

    def no_undo_log(self, target_dir):
        print(f"  No undo log found in '{target_dir}'.")
        print("  Run SortingHat on the folder first before attempting an undo.")

    def undo_summary(self, r):
        print("-" * 60)
        print(f"\n  {'Would restore' if r.dry_run else 'Restored'} {r.restored} file(s).")
        if r.failed:
            print(f"  Failed   {r.failed} file(s) (already missing or locked).")
        if r.blocked:
            print(f"  Blocked  {r.blocked} entr{'y' if r.blocked == 1 else 'ies'} pointing outside the target folder.")
        if r.cleaned:
            print(f"  Cleaned  {r.cleaned} empty category folder(s).")
        if r.dry_run:
            print("  Dry run  - nothing was moved and the undo log is unchanged.")
        elif r.remaining:
            print(f"  History  {r.remaining} earlier run(s) still available to undo.")
        print()

    def note(self, message):
        if self.verbosity == Verbosity.VERBOSE:
            print(f"  {message}\n")


# ── Interactive menu ──────────────────────────────────────────────────────────

def describe_undo_state(target_dir: Path) -> str:
    """One-line description of what an undo would currently restore."""
    runs = read_undo_runs(target_dir / UNDO_LOG_FILENAME)
    if not runs:
        return "nothing to undo"
    moves = len(runs[-1].get("moves", []))
    extra = f", {len(runs) - 1} older run(s) behind it" if len(runs) > 1 else ""
    return f"{moves} file(s) from the last sort{extra}"


def prompt_for_target(current: Path) -> Path:
    """Ask for a new target folder, keeping *current* if the answer is unusable."""
    raw = input("\n  Folder path (blank to keep current): ").strip().strip('"')
    if not raw:
        return current
    candidate = Path(raw).expanduser().resolve()
    if not candidate.is_dir():
        print(f"\n  '{candidate}' does not exist or is not a directory - keeping the current target.")
        return current
    return candidate


def run_interactive_menu(
    target_dir: Path,
    verbosity: Verbosity,
    exclude_patterns: list[str] | None = None,
    ext_map: dict[str, str] | None = None,
) -> None:
    """
    Menu loop shown when SortingHat is launched with no arguments — chiefly the
    compiled .exe, where a double-click would otherwise sort immediately with no
    chance to confirm the target or reach for undo.
    """
    while True:
        print()
        print("-" * 60)
        print(f"\n  Target  : {target_dir}")
        print(f"  Undo    : {describe_undo_state(target_dir)}\n")
        for option in (
            "[1]  Preview sort   (dry run, nothing is moved)",
            "[2]  Sort now",
            "[3]  Preview undo   (dry run, nothing is moved)",
            "[4]  Undo last sort",
            "[5]  Change target folder",
            "[0]  Exit",
        ):
            print(f"    {colourise(option)}")
        print()

        try:
            choice = input("  Choose an option: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Cancelled.\n")
            return

        print()
        if choice == "0":
            print("  Nothing else to do - goodbye.\n")
            return
        if choice == "5":
            target_dir = prompt_for_target(target_dir)
            continue
        if choice in {"3", "4"}:
            undo_last_sort(target_dir, verbosity, dry_run=(choice == "3"))
            continue
        if choice in {"1", "2"}:
            dry_run = choice == "1"
            print("-" * 60)
            print()
            result = sort_directory(
                target_dir,
                dry_run=dry_run,
                exclude_patterns=exclude_patterns,
                verbosity=verbosity,
                ext_map=ext_map,
            )
            print_summary(result, dry_run=dry_run, verbosity=verbosity)
            continue

        print(f"  '{choice}' is not one of the options - pick a number from 0 to 5.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    print(BANNER)

    parser = argparse.ArgumentParser(
        description="SortingHat - A simple tool for organizing messy folders."
    )
    parser.add_argument(
        "target_path", type=str, nargs="?",
        help="Path to the folder you want to organize (default: ~/Downloads).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview what files would be moved without making any actual changes. "
             "Can be combined with --undo to preview a restore.",
    )
    parser.add_argument(
        "--undo", action="store_true",
        help="Reverse the last sort run in the target folder. Repeat to walk "
             "further back through the sort history.",
    )
    parser.add_argument(
        "--exclude", metavar="PATTERN", action="append", default=[],
        help="Glob pattern of filenames to skip. Can be repeated. Example: --exclude '*.tmp'",
    )
    parser.add_argument(
        "--config", metavar="FILE",
        help="Path to a JSON file that adds or extends extension-to-category mappings.",
    )
    parser.add_argument(
        "--menu", action="store_true",
        help="Show the interactive menu instead of sorting straight away. This is "
             "the default when the compiled .exe is launched with no arguments.",
    )
    parser.add_argument(
        "--no-menu", action="store_true",
        help="Sort immediately even when no arguments are given (the pre-menu behaviour).",
    )
    parser.add_argument(
        "--gui", action="store_true",
        help="Launch the graphical interface instead of the terminal.",
    )
    verbosity_group = parser.add_mutually_exclusive_group()
    verbosity_group.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-file output; show only the final summary.",
    )
    verbosity_group.add_argument(
        "--verbose", action="store_true",
        help="Show additional detail including system and excluded files.",
    )
    args = parser.parse_args()

    verbosity = Verbosity.QUIET if args.quiet else Verbosity.VERBOSE if args.verbose else Verbosity.NORMAL
    # Resolved up front so undo logs always record absolute paths — a log written
    # from one working directory has to stay valid when undone from another.
    target_dir = (Path(args.target_path) if args.target_path else Path.home() / "Downloads").resolve()

    if not target_dir.exists() or not target_dir.is_dir():
        print(f"  Error: '{target_dir}' does not exist or is not a directory.")
        _wait_for_exit()
        sys.exit(1)

    # ── GUI mode ──────────────────────────────────────────────────────────────
    # Imported lazily so the terminal path never pays the Tkinter import cost.
    # The console .exe is built without Tkinter to stay lean, so the import can
    # legitimately fail there — fall back to a pointer rather than a traceback.
    if args.gui:
        try:
            import sortinghat_gui
        except ImportError:
            print("  The graphical interface isn't available in this build.")
            print("  Use SortingHat-GUI.exe, or run from source with Python (Tkinter included).")
            _wait_for_exit()
            sys.exit(1)
        sortinghat_gui.main(target_dir)
        return

    # ── Interactive mode ──────────────────────────────────────────────────────
    # A double-clicked .exe gets the menu; an explicit request gets it anywhere.
    # Any real instruction on the command line (a path, --undo, --dry-run) means
    # the user already said what they want, so it is honoured directly.
    launched_bare = not any([args.target_path, args.undo, args.dry_run])
    if args.menu or (getattr(sys, "frozen", False) and launched_bare and not args.no_menu):
        ext_map = build_ext_map(load_config(Path(args.config)) if args.config else None)
        # No _wait_for_exit here: leaving the menu is already a deliberate choice,
        # so a second "Press Enter to exit" would just be one keypress too many.
        run_interactive_menu(target_dir, verbosity, args.exclude, ext_map)
        return

    # ── Undo mode ─────────────────────────────────────────────────────────────
    if args.undo:
        print(f"  Target  : {target_dir}")
        print(f"  Mode    : {'UNDO DRY RUN  (no files will be moved)' if args.dry_run else 'UNDO'}\n")
        undo_last_sort(target_dir, verbosity, dry_run=args.dry_run)
        _wait_for_exit()
        return

    # ── Sort mode ─────────────────────────────────────────────────────────────
    ext_map = build_ext_map(load_config(Path(args.config)) if args.config else None)

    print(f"  Target  : {target_dir}")
    print(f"  Mode    : {'DRY RUN  (no files will be moved)' if args.dry_run else 'LIVE'}")
    if args.exclude:
        print(f"  Exclude : {', '.join(args.exclude)}")
    if args.config:
        print(f"  Config  : {args.config}")
    print()
    print("-" * 60)
    print()

    result = sort_directory(
        target_dir,
        dry_run=args.dry_run,
        exclude_patterns=args.exclude,
        verbosity=verbosity,
        ext_map=ext_map,
    )
    print_summary(result, dry_run=args.dry_run, verbosity=verbosity)
    _wait_for_exit()


if __name__ == "__main__":
    main()
