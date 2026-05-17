@echo off
:: Windrose Save Recovery Tool - EXE Builder
:: Run this from inside the windrose_tool\ folder

echo.
echo  Windrose Save Recovery Tool - Build Script
echo  -------------------------------------------
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found. Install Python 3.12+ and add it to PATH.
    pause & exit /b 1
)

:: Install/upgrade dependencies
echo  [1/3] Installing dependencies...
pip install -r requirements.txt --quiet
pip install pyinstaller --quiet
echo        Done.
echo.

:: Build
echo  [2/3] Building executable...
pyinstaller windrose_tool.spec --clean --noconfirm
echo.

:: Check output
if exist "dist\WindroseSaveRecovery.exe" (
    echo  [3/3] Success!
    echo.
    echo  Output: dist\WindroseSaveRecovery.exe
    echo.
    echo  You can distribute that single .exe file.
    echo  It requires no Python installation to run.
) else (
    echo  [3/3] Build failed - check the output above for errors.
)

echo.
pause
