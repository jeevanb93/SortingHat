# SortingHat 🧙‍♂️

SortingHat is a simple, lightweight Python CLI tool designed to bring order to the chaos of your messy folders (especially your `Downloads` directory). It automatically categorizes and moves files into organized subdirectories based on their file extensions.

## Features

- **Automated Categorization**: Sorts files into logical folders like `Documents`, `Pictures`, `Videos`, `Music`, `Compressed`, `Installers`, `Torrents`, and `Misc`.
- **Smart Collision Handling**: If a file with the same name already exists in the destination folder, SortingHat safely renames the new file (e.g., `file (1).txt`) to ensure nothing is ever overwritten or lost.
- **Dry Run Mode**: Safely preview what files will be moved and where, without making any actual changes to your filesystem.
- **Undo Support**: Reverse the last sorting operation effortlessly in case of a mistake.
- **Custom Configuration**: Use a JSON file to add new categories or map additional file extensions.
- **Exclude Patterns**: Skip specific files using glob patterns (e.g., `--exclude '*.tmp'`).
- **Adjustable Verbosity**: Run silently with `--quiet` or get detailed logs with `--verbose`.
- **System File Filtering**: Automatically ignores dotfiles and OS artefacts like `desktop.ini` and `Thumbs.db`.
- **No External Dependencies**: Uses only standard Python libraries (`argparse`, `fnmatch`, `shutil`, `pathlib`).

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

### Exclude Files
Use `--exclude` to skip files matching a glob pattern. The flag can be repeated to add multiple patterns:
```bash
python sortinghat.py --exclude "*.tmp"
python sortinghat.py --exclude "*.tmp" --exclude "Thumbs*"
```

### Undo Last Sort
If you make a mistake, you can undo the last live run in a folder. SortingHat saves a hidden `.sortinghat_undo.json` log which allows it to move files back to their original locations:
```bash
python sortinghat.py --undo
```

### Custom Configuration
You can define your own file categories or add new extensions to existing categories using a JSON config file. 

Create a `config.json` (see `example_config.json` for reference):
```json
{
    "Code": [".py", ".js", ".html", ".css"],
    "Music": [".mid"]
}
```
Then run SortingHat with the `--config` flag:
```bash
python sortinghat.py --config config.json
```

### Verbosity Options
By default, SortingHat prints each file it moves. 
- Use `--quiet` to suppress per-file output and only see the final summary table.
- Use `--verbose` to see additional details, such as ignored system files and excluded files.
```bash
python sortinghat.py --quiet
python sortinghat.py --verbose
```

## File Categories

SortingHat maps extensions to the following categories:

| Category | File Extensions |
| :--- | :--- |
| **Compressed** | `.zip`, `.rar`, `.7z`, `.tar`, `.gz`, `.bz2`, `.xz`, `.zst` |
| **Documents** | `.pdf`, `.docx`, `.doc`, `.txt`, `.xlsx`, `.xls`, `.pptx`, `.ppt`, `.csv`, `.epub`, `.odt`, `.rtf`, `.md`, `.json`, `.xml`, `.pages` |
| **Installers** | `.exe`, `.msi`, `.dmg`, `.pkg`, `.deb`, `.rpm`, `.appimage` |
| **Music** | `.mp3`, `.wav`, `.aac`, `.flac`, `.ogg`, `.opus`, `.m4a`, `.wma`, `.aiff` |
| **Pictures** | `.jpg`, `.jpeg`, `.png`, `.gif`, `.svg`, `.bmp`, `.heic`, `.tiff`, `.tif`, `.webp`, `.ico`, `.raw`, `.cr2`, `.nef` |
| **Videos** | `.mp4`, `.mkv`, `.avi`, `.mov`, `.wmv`, `.webm`, `.m4v`, `.flv` |
| **Torrents** | `.torrent` |
| **Misc** | Any extension not listed above. |

*(Note: Existing subdirectories in the target folder, dotfiles, and OS system files are automatically ignored.)*

## Building a Standalone Executable

If you want to run SortingHat without needing Python installed, you can build a standalone Windows executable using PyInstaller.

1. Install PyInstaller:
   ```bash
   pip install pyinstaller
   ```
2. Build the `.exe`:
   ```bash
   pyinstaller --onefile sortinghat.py
   ```
3. Your new `sortinghat.exe` will be available in the `dist` folder. The terminal window will stay open after the run completes, prompting you to press Enter before closing.
