import argparse
import os
import sys
import shutil
from pathlib import Path

EXTENSION_MAPPING = {
    "Compressed": [".zip", ".rar", ".7z", ".tar", ".gz"],
    "Documents": [".pdf", ".docx", ".doc", ".txt", ".xlsx", ".xls", ".pptx", ".ppt", ".csv"],
    "Music": [".mp3", ".wav", ".aac", ".flac"],
    "Pictures": [".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp", ".heic"],
    "Videos": [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"],
    "Torrents": [".torrent"],
}

def get_category(extension):
    extension = extension.lower()
    for category, exts in EXTENSION_MAPPING.items():
        if extension in exts:
            return category
    return "Misc"

def handle_collision(dest_file_path):
    if not dest_file_path.exists():
        return dest_file_path
        
    stem = dest_file_path.stem
    suffix = dest_file_path.suffix
    directory = dest_file_path.parent
    
    counter = 1
    while True:
        new_name = f"{stem} ({counter}){suffix}"
        new_path = directory / new_name
        if not new_path.exists():
            return new_path
        counter += 1

def main():
    parser = argparse.ArgumentParser(description="SortingHat - A simple tool to organizing messy folders.")
    
    parser.add_argument("target_path", type=str, nargs='?', help="The path to the folder you want to organize.")
    parser.add_argument("--dry-run", action="store_true", help="Preview what files would be moved without actually making changes.")
    
    args = parser.parse_args()
    
    target_dir = Path(args.target_path) if args.target_path else Path.home() / "Downloads"
    
    if not target_dir.exists() or not target_dir.is_dir():
        print(f"Error: The path '{target_dir}' does not exist or is not a directory.")
        sys.exit(1)
        
    print(f"SortingHat is preparing to analyze: {target_dir}")
    if args.dry_run:
        print("[DRY RUN MODE ENABLED - No files will actually be moved]\n")
        
    # Core scanning and moving logic
    moved_count = 0
    for file_path in target_dir.iterdir():
        # Only process files, ignore directories
        if not file_path.is_file():
            continue
            
        category = get_category(file_path.suffix)
        dest_folder = target_dir / category
        dest_file_path = dest_folder / file_path.name
        
        # Determine the final path for the file, handling collisions
        final_dest_path = handle_collision(dest_file_path)
        
        if args.dry_run:
            if final_dest_path.name != file_path.name:
                print(f"Would move: '{file_path.name}' -> '{category}/{final_dest_path.name}' (Renamed to avoid collision)")
            else:
                print(f"Would move: '{file_path.name}' -> '{category}/{final_dest_path.name}'")
            moved_count += 1
        else:
            if not dest_folder.exists():
                dest_folder.mkdir(parents=True, exist_ok=True)
                
            if final_dest_path.name != file_path.name:
                print(f"Moving: '{file_path.name}' -> '{category}/{final_dest_path.name}' (Renamed to avoid collision)")
            else:
                print(f"Moving: '{file_path.name}' -> '{category}/{final_dest_path.name}'")
            
            shutil.move(str(file_path), str(final_dest_path))
            moved_count += 1
            
    print(f"\nSortingHat finished! Processed {moved_count} files.")

if __name__ == "__main__":
    main()
