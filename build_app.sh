#!/usr/bin/env bash
#
# Build SortingHat executables on macOS (or Linux) with PyInstaller.
# This mirrors build_exe.bat. Run it ON the target OS — PyInstaller cannot
# cross-compile, so a macOS app must be built on a Mac.
#
#   chmod +x build_app.sh && ./build_app.sh
#
# -u is intentionally omitted: `source .venv/bin/activate` references unset vars.
set -eo pipefail
cd "$(dirname "$0")"

# Homebrew / system Python on macOS is "externally managed" (PEP 668) and refuses
# pip installs into it. Build inside a local virtual environment instead — clean,
# self-contained, and it leaves the system Python untouched.
echo "== Preparing build environment (.venv) =="
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate
python -m pip install --quiet --upgrade pip pyinstaller

if ! python -c "import tkinter" >/dev/null 2>&1; then
  echo "   WARNING: Tkinter is not available in this Python, so the GUI build will fail."
  echo "            Install it (e.g. 'brew install python-tk') and re-run. The console"
  echo "            build below will still succeed."
fi

echo "== Closing any running SortingHat processes =="
pkill -f "SortingHat-GUI" 2>/dev/null || true
pkill -f "dist/SortingHat" 2>/dev/null || true

echo "== Ensuring icons exist =="
# Only generate if missing. The .png/.ico are committed, and regenerating them
# just produces different-but-identical bytes (platform zlib differences), which
# shows up as pointless pending changes. Run tools/make_icon.py by hand to redraw.
if [ ! -f assets/sortinghat.png ]; then
  python tools/make_icon.py
fi

# On macOS, turn the PNG into a proper .icns for the .app bundle icon. Skipped on
# Linux (no iconutil) — the app still gets its window icon at runtime via iconphoto.
ICON_ARG=()
if command -v iconutil >/dev/null 2>&1 && command -v sips >/dev/null 2>&1; then
  echo "== Building macOS .icns from the PNG =="
  ICONSET="$(mktemp -d)/sortinghat.iconset"
  mkdir -p "$ICONSET"
  for size in 16 32 128 256 512; do
    sips -z "$size" "$size"           assets/sortinghat.png --out "$ICONSET/icon_${size}x${size}.png"    >/dev/null
    sips -z "$((size*2))" "$((size*2))" assets/sortinghat.png --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o assets/sortinghat.icns
  ICON_ARG=(--icon assets/sortinghat.icns)
fi

echo "== Building console executable (SortingHat) =="
# Exclude Tkinter so the terminal build stays lean; --gui there points to the GUI app.
python -m PyInstaller --onefile --name "SortingHat" \
  --exclude-module sortinghat_gui --exclude-module tkinter --exclude-module _tkinter \
  "${ICON_ARG[@]}" --noconfirm sortinghat.py

echo "== Building GUI app (SortingHat-GUI) =="
# NOTE: --add-data uses ':' as the separator on macOS/Linux (';' on Windows).
python -m PyInstaller --onefile --windowed --name "SortingHat-GUI" \
  --add-data "assets/sortinghat.png:assets" \
  "${ICON_ARG[@]}" --noconfirm sortinghat_gui.py

echo ""
echo "== Done =="
echo "  dist/SortingHat          - terminal / menu"
echo "  dist/SortingHat-GUI.app  - desktop app (macOS); dist/SortingHat-GUI on Linux"
echo ""
echo "First launch on macOS: Gatekeeper blocks unsigned apps. Right-click the .app"
echo "and choose Open (once), or run:  xattr -dr com.apple.quarantine dist/SortingHat-GUI.app"
