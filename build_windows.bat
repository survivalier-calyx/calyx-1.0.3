@echo off
REM ============================================================
REM  Calyx - build a standalone Windows installer (.exe)
REM  The resulting .exe embeds its own Python interpreter:
REM  users do NOT need Python installed to run it.
REM  Run this script on a WINDOWS machine (double-click it,
REM  or "build_windows.bat" from a cmd prompt).
REM ============================================================

cd /d "%~dp0"

echo [1/3] Checking Python...
where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install it from https://python.org then retry.
    pause
    exit /b 1
)

echo [2/3] Creating build environment (.buildenv) and installing PyInstaller...
python -m venv .buildenv
.buildenv\Scripts\python -m pip install --upgrade pip pyinstaller

echo [3/3] Building Calyx-Installer.exe ...
.buildenv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "Calyx-Installer" ^
    --add-data "calyx.py;." ^
    --add-data "LICENSE;." ^
    --add-data "assets;assets" ^
    --add-data "examples;examples" ^
    installer.py

echo.
echo Done. Your executable is in: dist\Calyx-Installer.exe
echo Double-click it to launch the Calyx graphical installer.
pause
