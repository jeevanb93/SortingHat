from __future__ import annotations

import argparse
import fnmatch
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass, field
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
    "Compressed": [
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".zst",
    ],
    "Documents": [
        ".pdf", ".docx", ".doc", ".txt", ".xlsx", ".xls", ".pptx", ".ppt",
        ".csv", ".epub", ".odt", ".rtf", ".md", ".json", ".xml", ".pages",
    ],
    "Installers": [
        ".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".appimage",
    ],
    "Music": [
        ".mp3", ".wav", ".aac", ".flac", ".ogg", ".opus", ".m4a", ".wma", ".aiff",
    ],
    "Pictures": [
        ".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp", ".heic",
        ".tiff", ".tif", ".webp", ".ico", ".raw", ".cr2", ".nef",
    ],
    "Torrents": [
        ".torrent",
    ],
    "Videos": [
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".flv",
    ],
}

# O(1) reverse-lookup: extension -> category
EXT_TO_CATEGORY: dict[str, str] = {
    ext: cat for cat, exts in EXTENSION_MAPPING.items() for ext in exts
}

# Known OS/system files to silently ignore
SYSTEM_FILES: set[str] = {"desktop.ini", "thumbs.db"}


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class SortResult:
    """Accumulates counts and a per-category breakdown from a sort run."""
    moved:          int = 0
    skipped:        int = 0
    system_ignored: int = 0
    excluded:       int = 0
    category_counts: dict[str, int] = field(default_factory=dict)


# ── Core helpers ──────────────────────────────────────────────────────────────

def get_category(extension: str) -> str:
    """Return the category name for a given file extension."""
    return EXT_TO_CATEGORY.get(extension.lower(), "Misc")


def is_system_file(file_path: Path) -> bool:
    """Return True for dotfiles and known OS/system files that should not be sorted."""
    if file_path.name.startswith("."):
        return True
    if file_path.name.lower() in SYSTEM_FILES:
        return True
    return False


def is_excluded(file_path: Path, patterns: list[str]) -> bool:
    """Return True if the filename matches any user-supplied glob pattern."""
    return any(fnmatch.fnmatch(file_path.name, pattern) for pattern in patterns)


def handle_collision(
    dest_file_path: Path,
    occupied: set[Path] | None = None,
) -> Path:
    """
    Return a safe destination path that avoids:
      - Real files already on the filesystem.
      - Paths already claimed in this session (``occupied``),
        enabling accurate dry-run collision simulation.
    """
    if occupied is None:
        occupied = set()

    if not dest_file_path.exists() and dest_file_path not in occupied:
        return dest_file_path

    stem      = dest_file_path.stem
    suffix    = dest_file_path.suffix
    directory = dest_file_path.parent

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
) -> SortResult:
    """
    Scan *target_dir* and sort every file into category sub-folders.

    Returns a :class:`SortResult` with counts and a per-category breakdown.
    No filesystem changes are made when *dry_run* is ``True``.
    """
    if exclude_patterns is None:
        exclude_patterns = []

    result: SortResult = SortResult()
    category_counts: dict[str, int] = defaultdict(int)
    occupied: set[Path] = set()  # paths claimed this session (dry-run simulation)

    for file_path in sorted(target_dir.iterdir()):
        if not file_path.is_file():
            continue

        if is_system_file(file_path):
            result.system_ignored += 1
            continue

        if exclude_patterns and is_excluded(file_path, exclude_patterns):
            print(f"  [Excluded] {file_path.name}")
            result.excluded += 1
            print()
            continue

        category       = get_category(file_path.suffix)
        dest_folder    = target_dir / category
        final_dest     = handle_collision(dest_folder / file_path.name, occupied)
        renamed        = final_dest.name != file_path.name
        rename_note    = " (renamed to avoid collision)" if renamed else ""

        if dry_run:
            print(f"  [Preview]  {file_path.name}")
            print(f"             -> {category}/{final_dest.name}{rename_note}")
            occupied.add(final_dest)
            result.moved += 1
            category_counts[category] += 1
        else:
            dest_folder.mkdir(parents=True, exist_ok=True)
            print(f"  Moving  {file_path.name}")
            print(f"       -> {category}/{final_dest.name}{rename_note}")
            try:
                shutil.move(str(file_path), str(final_dest))
                result.moved += 1
                category_counts[category] += 1
            except PermissionError:
                print("  [SKIPPED] Permission denied — file may be in use.")
                result.skipped += 1
            except OSError as e:
                print(f"  [SKIPPED] OS error: {e}")
                result.skipped += 1

        print()

    result.category_counts = dict(category_counts)
    return result


# ── Output helpers ────────────────────────────────────────────────────────────

def print_summary(result: SortResult, dry_run: bool) -> None:
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
    if result.system_ignored:
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
        "--exclude", metavar="PATTERN", action="append", default=[],
        help=(
            "Glob pattern of filenames to skip. Can be repeated. "
            "Example: --exclude '*.tmp' --exclude 'Thumbs*'"
        ),
    )
    args = parser.parse_args()

    target_dir = Path(args.target_path) if args.target_path else Path.home() / "Downloads"

    if not target_dir.exists() or not target_dir.is_dir():
        print(f"  Error: '{target_dir}' does not exist or is not a directory.")
        _wait_for_exit()
        sys.exit(1)

    print(f"  Target  : {target_dir}")
    print(f"  Mode    : {'DRY RUN  (no files will be moved)' if args.dry_run else 'LIVE'}")
    if args.exclude:
        print(f"  Exclude : {', '.join(args.exclude)}")
    print()
    print("-" * 60)
    print()

    result = sort_directory(
        target_dir,
        dry_run=args.dry_run,
        exclude_patterns=args.exclude,
    )

    print_summary(result, dry_run=args.dry_run)
    _wait_for_exit()


if __name__ == "__main__":
    main()
