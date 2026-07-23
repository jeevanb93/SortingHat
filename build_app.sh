#!/usr/bin/env bash
#
# Build SortingHat executables on macOS (or Linux) with PyInstaller.
# This mirrors build_exe.bat. Run it ON the target OS — PyInstaller cannot
# cross-compile, so a macOS app must be built on a Mac.
#
#   chmod +x build_app.sh && ./build_app.sh
#
set -euo pipefail
cd "$(dirname "$0")"

echo "== Checking for PyInstaller =="
python3 -m pip install --quiet --upgrade pyinstaller

echo "== Closing any running SortingHat processes =="
pkill -f "SortingHat-GUI" 2>/dev/null || true
pkill -f "dist/SortingHat" 2>/dev/null || true

echo "== Generating icons (assets/sortinghat.png + .ico) =="
python3 tools/make_icon.py

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
python3 -m PyInstaller --onefile --name "SortingHat" \
  --exclude-module sortinghat_gui --exclude-module tkinter --exclude-module _tkinter \
  "${ICON_ARG[@]}" --noconfirm sortinghat.py

echo "== Building GUI app (SortingHat-GUI) =="
# NOTE: --add-data uses ':' as the separator on macOS/Linux (';' on Windows).
python3 -m PyInstaller --onefile --windowed --name "SortingHat-GUI" \
  --add-data "assets/sortinghat.png:assets" \
  "${ICON_ARG[@]}" --noconfirm sortinghat_gui.py

echo ""
echo "== Done =="
echo "  dist/SortingHat          - terminal / menu"
echo "  dist/SortingHat-GUI.app  - desktop app (macOS); dist/SortingHat-GUI on Linux"
echo ""
echo "First launch on macOS: Gatekeeper blocks unsigned apps. Right-click the .app"
echo "and choose Open (once), or run:  xattr -dr com.apple.quarantine dist/SortingHat-GUI.app"
