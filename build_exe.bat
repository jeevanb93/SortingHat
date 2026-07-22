@echo off
echo ===================================================
echo SortingHat - Standalone Executable Builder
echo ===================================================
echo.
echo Checking for PyInstaller...
pip install pyinstaller

echo.
echo Generating application icon...
python tools\make_icon.py

echo.
echo Building console executable (SortingHat.exe)...
REM Exclude Tkinter so the terminal build stays lean; --gui there points to the GUI exe.
pyinstaller --onefile --name "SortingHat" --icon "assets\sortinghat.ico" ^
  --exclude-module sortinghat_gui --exclude-module tkinter --exclude-module _tkinter ^
  --noconfirm sortinghat.py

echo.
echo Building GUI executable (SortingHat-GUI.exe)...
pyinstaller --onefile --windowed --name "SortingHat-GUI" --icon "assets\sortinghat.ico" --add-data "assets\sortinghat.ico;assets" --noconfirm sortinghat_gui.py

echo.
echo ===================================================
echo Build complete!
echo   dist\SortingHat.exe      - terminal / menu
echo   dist\SortingHat-GUI.exe  - desktop window
echo ===================================================
pause
