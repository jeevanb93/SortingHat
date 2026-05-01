import argparse
import sys
import shutil
from pathlib import Path
from collections import defaultdict

BANNER = r"""
 ____             _   _             _   _       _
/ ___|  ___  _ __| |_(_)_ __   __ _| | | | __ _| |_
\___ \ / _ \| '__| __| | '_ \ / _` | |_| |/ _` | __|
 ___) | (_) | |  | |_| | | | | (_| |  _  | (_| | |_
|____/ \___/|_|   \__|_|_| |_|\__, |_| |_|\__,_|\__|
                               |___/
"""

EXTENSION_MAPPING = {
    "Compressed": [".zip", ".rar", ".7z", ".tar", ".gz"],
    "Documents":  [".pdf", ".docx", ".doc", ".txt", ".xlsx", ".xls", ".pptx", ".ppt", ".csv"],
    "Music":      [".mp3", ".wav", ".aac", ".flac"],
    "Pictures":   [".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp", ".heic"],
    "Videos":     [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"],
    "Torrents":   [".torrent"],
}

# O(1) reverse-lookup: extension -> category
EXT_TO_CATEGORY = {ext: cat for cat, exts in EXTENSION_MAPPING.items() for ext in exts}

# Known Windows system files to silently ignore
SYSTEM_FILES = {"desktop.ini", "thumbs.db"}


def get_category(extension):
    return EXT_TO_CATEGORY.get(extension.lower(), "Misc")


def is_system_file(file_path):
    """Return True for dotfiles and known system/OS files that should not be sorted."""
    if file_path.name.startswith("."):
        return True
    if file_path.name.lower() in SYSTEM_FILES:
        return True
    return False


def handle_collision(dest_file_path, occupied=None):
    """
    Return a safe destination path that avoids:
      - Real files already on the filesystem.
      - Paths already claimed in this session (the `occupied` set),
        which enables accurate collision simulation during dry runs.
    """
    if occupied is None:
        occupied = set()

    if not dest_file_path.exists() and dest_file_path not in occupied:
        return dest_file_path

    stem = dest_file_path.stem
    suffix = dest_file_path.suffix
    directory = dest_file_path.parent

    counter = 1
    while True:
        new_name = f"{stem} ({counter}){suffix}"
        new_path = directory / new_name
        if not new_path.exists() and new_path not in occupied:
            return new_path
        counter += 1


def _wait_for_exit():
    """Pause before the window closes — only active when running as a compiled .exe."""
    if getattr(sys, "frozen", False):
        input("\nPress Enter to exit...")


def main():
    print(BANNER)

    parser = argparse.ArgumentParser(
        description="SortingHat - A simple tool for organizing messy folders."
    )
    parser.add_argument(
        "target_path", type=str, nargs="?",
        help="Path to the folder you want to organize."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview what files would be moved without making any actual changes."
    )
    args = parser.parse_args()

    target_dir = Path(args.target_path) if args.target_path else Path.home() / "Downloads"

    if not target_dir.exists() or not target_dir.is_dir():
        print(f"  Error: '{target_dir}' does not exist or is not a directory.")
        _wait_for_exit()
        sys.exit(1)

    print(f"  Target : {target_dir}")
    print(f"  Mode   : {'DRY RUN  (no files will be moved)' if args.dry_run else 'LIVE'}")
    print()
    print("-" * 60)
    print()

    moved_count = 0
    skipped_count = 0
    system_skipped = 0
    category_counts = defaultdict(int)

    # Paths claimed in this session — used for accurate dry-run collision detection
    occupied = set()

    for file_path in sorted(target_dir.iterdir()):
        if not file_path.is_file():
            continue

        if is_system_file(file_path):
            system_skipped += 1
            continue

        category = get_category(file_path.suffix)
        dest_folder = target_dir / category
        dest_file_path = dest_folder / file_path.name
        final_dest_path = handle_collision(dest_file_path, occupied)

        renamed = final_dest_path.name != file_path.name
        rename_note = " (renamed to avoid collision)" if renamed else ""

        if args.dry_run:
            print(f"  [Preview]  {file_path.name}")
            print(f"             -> {category}/{final_dest_path.name}{rename_note}")
            occupied.add(final_dest_path)
            moved_count += 1
            category_counts[category] += 1
        else:
            if not dest_folder.exists():
                dest_folder.mkdir(parents=True, exist_ok=True)

            print(f"  Moving  {file_path.name}")
            print(f"       -> {category}/{final_dest_path.name}{rename_note}")

            try:
                shutil.move(str(file_path), str(final_dest_path))
                moved_count += 1
                category_counts[category] += 1
            except PermissionError:
                print(f"  [SKIPPED] Permission denied — file may be in use.")
                skipped_count += 1
            except OSError as e:
                print(f"  [SKIPPED] OS error: {e}")
                skipped_count += 1

        print()

    # ── Summary ───────────────────────────────────────────────────────────────
    print("-" * 60)
    action = "Would move" if args.dry_run else "Moved"
    print(f"\n  {action} {moved_count} file(s).\n")

    if category_counts:
        print("  Breakdown:")
        for cat, count in sorted(category_counts.items()):
            bar = "#" * count
            print(f"    {cat:<14} {bar}  ({count})")
        print()

    if skipped_count:
        print(f"  Skipped  : {skipped_count} file(s) due to errors.")
    if system_skipped:
        print(f"  Ignored  : {system_skipped} system/hidden file(s).")

    _wait_for_exit()


if __name__ == "__main__":
    main()
