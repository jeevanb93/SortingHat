@echo off
echo ===================================================
echo SortingHat - Standalone Executable Builder
echo ===================================================
echo.
echo Checking for PyInstaller...
pip install pyinstaller

echo.
echo Building SortingHat Executable...
pyinstaller --onefile --name "SortingHat" sortinghat.py

echo.
echo ===================================================
echo Build complete! 
echo You can find SortingHat.exe in the 'dist' folder.
echo ===================================================
pause
