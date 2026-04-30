# SortingHat 🧙‍♂️

SortingHat is a simple, lightweight Python CLI tool designed to bring order to the chaos of your messy folders (especially your `Downloads` directory). It automatically categorizes and moves files into organized subdirectories based on their file extensions.

## Features

- **Automated Categorization**: Sorts files into logical folders like `Documents`, `Pictures`, `Videos`, `Music`, `Compressed`, and `Torrents`.
- **Smart Collision Handling**: If a file with the same name already exists in the destination folder, SortingHat safely renames the new file (e.g., `file (1).txt`) to ensure nothing is ever overwritten or lost.
- **Dry Run Mode**: Safely preview what files will be moved and where, without making any actual changes to your filesystem.
- **No External Dependencies**: Uses only standard Python libraries (`argparse`, `shutil`, `pathlib`).

## Installation

You can install SortingHat as a proper command-line tool from the project root:

```bash
pip install -e .
```

After installation, the `sortinghat` command will be available directly in your terminal without needing to prefix it with `python`.

## Usage

You can run the script directly from your terminal.

### Basic Usage
If you run the script without any arguments, it will automatically default to organizing your user's **Downloads** folder:
```bash
python sortinghat.py
```

### Specify a Target Folder
To organize a specific folder, pass the folder path as an argument. Use quotes if the path contains spaces:
```bash
python sortinghat.py "C:\Path\To\Your\Messy\Folder"
```

### Dry Run (Preview Changes)
To see what the tool *would* do without actually moving any files, use the `--dry-run` flag:
```bash
python sortinghat.py --dry-run
python sortinghat.py "C:\Path\To\Your\Messy\Folder" --dry-run
```

## File Categories

SortingHat currently maps extensions to the following categories:

| Category | File Extensions |
| :--- | :--- |
| **Compressed** | `.zip`, `.rar`, `.7z`, `.tar`, `.gz` |
| **Documents** | `.pdf`, `.docx`, `.doc`, `.txt`, `.xlsx`, `.xls`, `.pptx`, `.ppt`, `.csv` |
| **Music** | `.mp3`, `.wav`, `.aac`, `.flac` |
| **Pictures** | `.jpg`, `.jpeg`, `.png`, `.gif`, `.svg`, `.bmp`, `.heic` |
| **Videos** | `.mp4`, `.mkv`, `.avi`, `.mov`, `.wmv`, `.webm` |
| **Torrents** | `.torrent` |
| **Misc** | Any file extension not listed above will go here. |

*(Note: Existing subdirectories in the target folder are ignored and not moved.)*

## Building a Standalone Executable

If you want to run SortingHat without needing to use the Python command line directly, you can build a standalone Windows executable using PyInstaller. 

1. Install PyInstaller:
   ```bash
   pip install pyinstaller
   ```
2. Build the `.exe` (a `SortingHat.spec` file may be used if already generated, otherwise run):
   ```bash
   pyinstaller --onefile sortinghat.py
   ```
3. Your new `sortinghat.exe` will be available in the `dist` folder. 

