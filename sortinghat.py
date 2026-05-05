from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
import sys
from collections import defaultdict
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


# ── Config & extension-map helpers ────────────────────────────────────────────

def load_config(config_path: Path) -> dict[str, list[str]]:
    """Parse a JSON config file and return its category -> extensions mapping."""
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
    if not dest_file_path.exists() and dest_file_path not in occupied:
        return dest_file_path
    stem, suffix, directory = dest_file_path.stem, dest_file_path.suffix, dest_file_path.parent
    counter = 1
    while True:
        new_path = directory / f"{stem} ({counter}){suffix}"
        if not new_path.exists() and new_path not in occupied:
            return new_path
        counter += 1


# ── Sorting logic ─────────────────────────────────────────────────────────────

def sort_directory(
    target_dir: Path,
    dry_run: bool = False,
    exclude_patterns: list[str] | None = None,
    verbosity: Verbosity = Verbosity.NORMAL,
    ext_map: dict[str, str] | None = None,
) -> SortResult:
    """
    Scan *target_dir* and sort every file into category sub-folders.
    Returns a :class:`SortResult` with counts and a per-category breakdown.
    On a live run, writes an undo log to *target_dir* so the sort can be reversed.
    """
    if exclude_patterns is None:
        exclude_patterns = []
    if ext_map is None:
        ext_map = build_ext_map()

    result: SortResult = SortResult()
    category_counts: dict[str, int] = defaultdict(int)
    occupied: set[Path] = set()
    undo_log: list[dict[str, str]] = []

    for file_path in sorted(target_dir.iterdir()):
        if not file_path.is_file():
            continue

        if is_system_file(file_path):
            result.system_ignored += 1
            if verbosity == Verbosity.VERBOSE:
                print(f"  [System]   {file_path.name}\n")
            continue

        if exclude_patterns and is_excluded(file_path, exclude_patterns):
            result.excluded += 1
            if verbosity != Verbosity.QUIET:
                print(f"  [Excluded] {file_path.name}\n")
            continue

        category    = get_category(file_path.suffix, ext_map)
        dest_folder = target_dir / category
        final_dest  = handle_collision(dest_folder / file_path.name, occupied)
        renamed     = final_dest.name != file_path.name
        rename_note = " (renamed to avoid collision)" if renamed else ""

        if dry_run:
            if verbosity != Verbosity.QUIET:
                print(f"  [Preview]  {file_path.name}")
                print(f"             -> {category}/{final_dest.name}{rename_note}\n")
            occupied.add(final_dest)
            result.moved += 1
            category_counts[category] += 1
        else:
            dest_folder.mkdir(parents=True, exist_ok=True)
            if verbosity != Verbosity.QUIET:
                print(f"  Moving  {file_path.name}")
                print(f"       -> {category}/{final_dest.name}{rename_note}\n")
            try:
                shutil.move(str(file_path), str(final_dest))
                undo_log.append({"src": str(file_path), "dst": str(final_dest)})
                result.moved += 1
                category_counts[category] += 1
            except PermissionError:
                print("  [SKIPPED] Permission denied — file may be in use.\n")
                result.skipped += 1
            except OSError as e:
                print(f"  [SKIPPED] OS error: {e}\n")
                result.skipped += 1

    result.category_counts = dict(category_counts)

    # Write undo log on live runs
    if not dry_run and undo_log:
        log_path = target_dir / UNDO_LOG_FILENAME
        log_path.write_text(
            json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(),
                        "target": str(target_dir), "moves": undo_log}, indent=2),
            encoding="utf-8",
        )
        if verbosity == Verbosity.VERBOSE:
            print(f"  Undo log written to: {log_path}\n")

    return result


# ── Undo logic ────────────────────────────────────────────────────────────────

def undo_last_sort(target_dir: Path, verbosity: Verbosity) -> None:
    """Reverse the last sort run by reading the undo log in *target_dir*."""
    log_path = target_dir / UNDO_LOG_FILENAME
    if not log_path.exists():
        print(f"  No undo log found in '{target_dir}'.")
        print("  Run SortingHat on the folder first before attempting an undo.")
        return

    log_data  = json.loads(log_path.read_text(encoding="utf-8"))
    moves     = log_data.get("moves", [])
    timestamp = log_data.get("timestamp", "unknown")

    print(f"  Undoing {len(moves)} move(s) from {timestamp}...\n")
    print("-" * 60)
    print()

    undone, failed = 0, 0
    for entry in reversed(moves):
        src, dst = Path(entry["src"]), Path(entry["dst"])
        if not dst.exists():
            if verbosity != Verbosity.QUIET:
                print(f"  [Missing]  '{dst.name}' no longer exists — skipping.\n")
            failed += 1
            continue
        final_src = handle_collision(src)
        if verbosity != Verbosity.QUIET:
            print(f"  Restoring  {dst.name}")
            print(f"         ->  {final_src}\n")
        try:
            shutil.move(str(dst), str(final_src))
            undone += 1
        except (PermissionError, OSError) as e:
            print(f"  [FAILED]   Could not restore '{dst.name}': {e}\n")
            failed += 1

    log_path.unlink()  # prevent double-undo
    print("-" * 60)
    print(f"\n  Restored {undone} file(s).")
    if failed:
        print(f"  Failed   {failed} file(s) (already missing or locked).")
    print()


# ── Output helpers ────────────────────────────────────────────────────────────

def print_summary(result: SortResult, dry_run: bool, verbosity: Verbosity) -> None:
    """Render the final summary table to stdout."""
    print("-" * 60)
    action = "Would move" if dry_run else "Moved"

    if result.category_counts:
        BAR_WIDTH = 20
        max_count = max(result.category_counts.values())
        total     = sum(result.category_counts.values())

        print(f"\n  {action} {total} file(s).\n")
        print(f"  {'Category':<14}  {'':20}  Count")
        print(f"  {'-'*14}  {'-'*20}  -----")
        for cat, count in sorted(result.category_counts.items()):
            filled = round((count / max_count) * BAR_WIDTH)
            bar    = "#" * filled + "-" * (BAR_WIDTH - filled)
            print(f"  {cat:<14}  [{bar}]  {count}")
        print(f"  {'-'*14}  {' '*20}  -----")
        print(f"  {'Total':<14}  {' '*20}  {total}")
    else:
        print(f"\n  {action} 0 file(s).")

    if result.skipped:
        print(f"\n  Skipped  : {result.skipped} file(s) due to errors.")
    if result.excluded:
        print(f"  Excluded : {result.excluded} file(s) matched --exclude pattern(s).")
    if result.system_ignored and verbosity != Verbosity.QUIET:
        print(f"  Ignored  : {result.system_ignored} system/hidden file(s).")
    print()


def _wait_for_exit() -> None:
    """Pause before the window closes — only active when running as a compiled .exe."""
    if getattr(sys, "frozen", False):
        input("\nPress Enter to exit...")


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
        help="Preview what files would be moved without making any actual changes.",
    )
    parser.add_argument(
        "--undo", action="store_true",
        help="Reverse the last sort run in the target folder.",
    )
    parser.add_argument(
        "--exclude", metavar="PATTERN", action="append", default=[],
        help="Glob pattern of filenames to skip. Can be repeated. Example: --exclude '*.tmp'",
    )
    parser.add_argument(
        "--config", metavar="FILE",
        help="Path to a JSON file that adds or extends extension-to-category mappings.",
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
    target_dir = Path(args.target_path) if args.target_path else Path.home() / "Downloads"

    if not target_dir.exists() or not target_dir.is_dir():
        print(f"  Error: '{target_dir}' does not exist or is not a directory.")
        _wait_for_exit()
        sys.exit(1)

    # ── Undo mode ─────────────────────────────────────────────────────────────
    if args.undo:
        print(f"  Target  : {target_dir}")
        print(f"  Mode    : UNDO\n")
        undo_last_sort(target_dir, verbosity)
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
