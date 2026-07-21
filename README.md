# SortingHat 🧙‍♂️

SortingHat is a simple, lightweight Python CLI tool designed to bring order to the chaos of your messy folders (especially your `Downloads` directory). It automatically categorizes and moves files into organized subdirectories based on their file extensions.

Nothing is ever overwritten, every live run can be undone, and every action can be previewed first.

## Features

- **Interactive Menu**: Launched with no arguments (or by double-clicking the `.exe`), SortingHat asks what you want to do instead of sorting straight away — preview, sort, undo, or change folder, each behind a number key, highlighted in green.
- **Automated Categorization**: Sorts files into logical folders like `Documents`, `Pictures`, `Videos`, `Music`, `Compressed`, `Installers`, `Torrents`, and `Misc`.
- **Smart Collision Handling**: If a file with the same name already exists in the destination folder, SortingHat safely renames the new file (e.g., `file (1).txt`) to ensure nothing is ever overwritten or lost.
- **Dry Run Mode**: Safely preview what files will be moved and where, without making any actual changes to your filesystem.
- **Undo Support**: Reverse sorting operations effortlessly in case of a mistake. Runs are stacked, so each `--undo` steps back one sort at a time, and it can be previewed with `--dry-run` first.
- **Custom Configuration**: Use a JSON file to add new categories or map additional file extensions.
- **Exclude Patterns**: Skip specific files using glob patterns (e.g., `--exclude '*.tmp'`).
- **Adjustable Verbosity**: Run silently with `--quiet` or get detailed logs with `--verbose`.
- **System File Filtering**: Automatically ignores dotfiles and OS artefacts like `desktop.ini` and `Thumbs.db`.
- **No External Dependencies**: Uses only standard Python libraries (`argparse`, `fnmatch`, `shutil`, `pathlib`).

## Requirements

- **Python 3.8 or newer** (developed and tested on 3.14). No third-party packages are needed to run the tool.
- **Windows, macOS, or Linux.** The tool is cross-platform; only the optional `.exe` build is Windows-specific.

To run SortingHat you need nothing but the single `sortinghat.py` file. Everything below — installing, building an `.exe` — is optional convenience.

---

## Running It

There are three ways to run SortingHat. Pick whichever suits you; they all accept the same options.

### 1. Straight from the source file

No installation at all. From the project root:

```bash
python sortinghat.py
```

### 2. As an installed command

Install once from the project root:

```bash
pip install -e .
```

The `-e` (editable) flag means the command always reflects the current source, so you can keep editing `sortinghat.py` without reinstalling. Afterwards the `sortinghat` command works from any directory:

```bash
sortinghat
sortinghat "C:\Path\To\Your\Messy\Folder" --dry-run
```

To remove it later: `pip uninstall sortinghat`.

### 3. As a standalone `.exe` (Windows, no Python required)

See [Building a Standalone Executable](#building-a-standalone-executable) below. Once built, double-click `dist\SortingHat.exe` or call it from a terminal like any other command.

> Throughout this README, examples are written as `python sortinghat.py ...`. Substitute `sortinghat ...` or `SortingHat.exe ...` if you installed or built it — the options are identical.

---

## Usage

### The Interactive Menu

Running SortingHat with **no arguments** — including double-clicking `SortingHat.exe` — opens a menu rather than sorting immediately, so a stray launch can never move your files:

```
  Target  : C:\Users\you\Downloads
  Undo    : 69 file(s) from the last sort

    [1]  Preview sort   (dry run, nothing is moved)
    [2]  Sort now
    [3]  Preview undo   (dry run, nothing is moved)
    [4]  Undo last sort
    [5]  Change target folder
    [0]  Exit

  Choose an option:
```

Type the number and press Enter. Notes:

- The menu **stays open after each action**, so you can preview, sort, then undo without relaunching.
- The `Undo` line always shows exactly what option `[4]` would restore, including how many older runs are stacked behind it.
- Option `[5]` accepts paths with or without surrounding quotes; a blank answer keeps the current folder.
- Options are printed in green. Colour switches off automatically when output is piped or redirected, and can be disabled entirely by setting the `NO_COLOR` environment variable.

A typical safe session is `[1]` to preview, `[2]` to commit, and `[4]` if you change your mind.

**Forcing the mode:** use `--menu` to open the menu from a normal terminal, or `--no-menu` to sort immediately even with no arguments.

### The Command Line

Passing any real instruction — a folder path, `--dry-run`, or `--undo` — skips the menu and does exactly what you asked.

#### Sort a specific folder
Pass the folder path as an argument. Use quotes if the path contains spaces:
```bash
python sortinghat.py "C:\Path\To\Your\Messy\Folder"
```

With no path given, SortingHat defaults to your user's **Downloads** folder:
```bash
python sortinghat.py --no-menu
```

#### Preview changes (dry run)
To see what the tool *would* do without moving anything:
```bash
python sortinghat.py --dry-run
python sortinghat.py "C:\Path\To\Your\Messy\Folder" --dry-run
```
The preview accounts for filename collisions, so the names it shows are the names you will actually get.

#### Exclude files
Use `--exclude` to skip files matching a glob pattern. The flag can be repeated:
```bash
python sortinghat.py --exclude "*.tmp"
python sortinghat.py --exclude "*.tmp" --exclude "Thumbs*"
```

#### Verbosity
By default, SortingHat prints each file it moves.
- `--quiet` suppresses per-file output, leaving only the final summary table.
- `--verbose` adds detail such as ignored system files, excluded files, and undo-log activity.
```bash
python sortinghat.py --quiet
python sortinghat.py --verbose
```

### What a Run Looks Like

```
  Moving  annual-report.pdf
       -> Documents/annual-report.pdf

  Moving  holiday-photo.jpg
       -> Pictures/holiday-photo.jpg

  Moving  invoice.pdf
       -> Documents/invoice (1).pdf (renamed to avoid collision)

------------------------------------------------------------

  Moved 69 file(s).

  Category                              Count
  --------------  --------------------  -----
  Compressed      [##------------------]  5
  Documents       [####################]  49
  Misc            [###-----------------]  8
  Pictures        [##------------------]  4
  Torrents        [#-------------------]  2
  Videos          [--------------------]  1
  --------------                        -----
  Total                                 69
```

The bars are scaled to the largest category, so you can see at a glance where the bulk of the clutter is.

---

## Undo

Every live run writes a hidden `.sortinghat_undo.json` log **into the folder it sorted**, recording where each file came from. Undo replays that log in reverse:

```bash
python sortinghat.py --undo
python sortinghat.py "C:\Path\To\Your\Messy\Folder" --undo
```

How it behaves:

- **Runs are stacked.** Each live sort appends a new entry, so sorting a folder repeatedly never destroys your earlier history. Each `--undo` walks back exactly one run — repeat it to keep unwinding.
- **The log is per-folder.** Undoing a sort of `Downloads` requires pointing `--undo` at `Downloads`.
- **Empty category folders are cleaned up** after a restore. Folders that still contain other files are left alone.
- **Files that have since been moved or deleted are reported and skipped**, never recreated.
- Once the last recorded run is undone, the log file is removed.

Undo can be previewed before you commit to it by combining it with `--dry-run`. Nothing is moved and the log is left intact:

```bash
python sortinghat.py --undo --dry-run
```

Because the log lives in the sorted folder, deleting `.sortinghat_undo.json` permanently discards the undo history for that folder.

---

## Custom Configuration

You can define your own file categories or add extensions to existing ones using a JSON config file. Keys are category (folder) names, values are lists of extensions:

```json
{
    "Code": [".py", ".js", ".ts", ".html", ".css", ".sql"],
    "Music": [".mid", ".midi"]
}
```

A ready-made `example_config.json` ships with the project. Pass it with `--config`:

```bash
python sortinghat.py --config example_config.json
```

Merge rules: a **new** category name creates a new folder; an **existing** category name has your extensions added to the built-in list rather than replacing it. Extensions are matched case-insensitively and should include the leading dot.

---

## Command Reference

| Option | Description |
| :--- | :--- |
| `target_path` | Folder to organize. Defaults to `~/Downloads`. |
| `--dry-run` | Preview without moving anything. Combine with `--undo` to preview a restore. |
| `--undo` | Reverse the last sort in the target folder. Repeat to walk further back. |
| `--exclude PATTERN` | Glob pattern of filenames to skip. Repeatable. |
| `--config FILE` | JSON file that adds or extends extension-to-category mappings. |
| `--menu` | Force the interactive menu. |
| `--no-menu` | Sort immediately even with no arguments. |
| `--quiet` | Summary only. Mutually exclusive with `--verbose`. |
| `--verbose` | Extra detail: system files, exclusions, undo-log activity. |
| `-h`, `--help` | Show the built-in help. |

| Environment variable | Effect |
| :--- | :--- |
| `NO_COLOR` | Set to any value to disable coloured output. |

---

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

Only files in the **top level** of the target folder are considered. Existing subdirectories, dotfiles, and OS system files (`desktop.ini`, `Thumbs.db`) are left untouched.

---

## Building a Standalone Executable

To run SortingHat on a machine without Python, build a single-file Windows executable with PyInstaller.

**The easy way** — run the included script from the project root, which installs PyInstaller if needed and builds with the right options:

```bash
build_exe.bat
```

**Manually**, if you prefer:

```bash
pip install pyinstaller
pyinstaller --onefile --name "SortingHat" sortinghat.py
```

Either way the result is **`dist\SortingHat.exe`** — a self-contained file you can copy anywhere. A `SortingHat.spec` file is generated on first build and can be reused directly:

```bash
pyinstaller SortingHat.spec
```

### Using the .exe

- **Double-click it** and you get the interactive menu; the window stays open until you choose `[0] Exit`.
- **Call it with arguments** from a terminal and it runs that command directly, then prompts you to press Enter before closing so you can read the output:
  ```
  SortingHat.exe "C:\Path\To\Your\Messy\Folder" --dry-run
  ```

### Rebuilding

If a build fails with `PermissionError: [WinError 5] Access is denied` on `dist\SortingHat.exe`, a copy is still running — close any open SortingHat windows and build again. `build/` and `dist/` are safe to delete at any time; they are regenerated on the next build.

---

## Development

Install the development dependencies and run the test suite from the project root:

```bash
pip install -e ".[dev]"
python -m pytest
```

The suite covers categorization, collision handling, config parsing, exclusions, the undo log format and stacking, empty-folder cleanup, colour fallback, and the interactive menu.

### Project Layout

| Path | Purpose |
| :--- | :--- |
| `sortinghat.py` | The entire tool — a single, dependency-free module. |
| `tests/test_sortinghat.py` | Pytest suite. |
| `pyproject.toml` | Packaging metadata and the `sortinghat` console-script entry point. |
| `example_config.json` | Sample custom category configuration. |
| `build_exe.bat` | One-step PyInstaller build script. |
| `SortingHat.spec`, `build/`, `dist/` | Generated on first build. Not tracked in git, and safe to delete. |

## License

MIT.
