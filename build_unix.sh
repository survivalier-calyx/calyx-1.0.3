#!/bin/sh
# ============================================================
#  Calyx - build a standalone macOS/Linux installer executable
#  The resulting binary embeds its own Python interpreter:
#  users do NOT need Python installed to run it.
#  Run this script on the TARGET OS itself:
#    ./build_unix.sh
#  (PyInstaller cannot cross-compile: build on macOS to get a
#   macOS app, build on Linux to get a Linux binary.)
# ============================================================
set -e
cd "$(dirname "$0")"

PY=python3
command -v "$PY" >/dev/null 2>&1 || { echo "python3 was not found. Install Python 3 then retry."; exit 1; }

echo "[1/3] Creating build environment (.buildenv) and installing PyInstaller..."
"$PY" -m venv .buildenv || {
    echo "Failed to create a venv. On Debian/Ubuntu, run: sudo apt install python3-venv"
    exit 1
}
.buildenv/bin/python -m pip install --upgrade pip pyinstaller

.buildenv/bin/python -c "import tkinter" 2>/dev/null || {
    echo "tkinter is missing. Install it then retry:"
    if [ "$(uname)" = "Darwin" ]; then
        echo "  brew install python-tk"
    else
        echo "  sudo apt install python3-tk"
    fi
    exit 1
}

echo "[2/3] Building Calyx-Installer ..."
.buildenv/bin/python -m PyInstaller --noconfirm --clean --onefile --windowed \
    --name "Calyx-Installer" \
    --add-data "calyx.py:." \
    --add-data "LICENSE:." \
    --add-data "assets:assets" \
    --add-data "examples:examples" \
    installer.py

echo
echo "[3/3] Done."
if [ "$(uname)" = "Darwin" ]; then
    echo "Your app is in: dist/Calyx-Installer.app (or dist/Calyx-Installer)"
    echo "Double-click it in Finder to launch the Calyx graphical installer."
    echo "(First launch: right-click -> Open, to bypass Gatekeeper since it is unsigned.)"
else
    echo "Your executable is in: dist/Calyx-Installer"
    echo "Make it executable if needed: chmod +x dist/Calyx-Installer"
    echo "Then double-click it (or run ./dist/Calyx-Installer) to launch the installer."
fi
