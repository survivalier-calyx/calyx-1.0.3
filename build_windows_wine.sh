#!/bin/sh
# ============================================================
#  Calyx - cross-build the Windows .exe from Linux, using Wine.
#  This installs a Windows Python inside a Wine prefix, then
#  runs PyInstaller inside Wine to produce a real Windows .exe.
#  More fragile than building on an actual Windows machine, but
#  works without leaving Linux.
#
#  Prerequisites (install once, needs sudo):
#    sudo apt install wine64 winetricks
# ============================================================
set -e
cd "$(dirname "$0")"

APP=Calyx-Installer
PYVER=3.11.9
export WINEPREFIX="$PWD/.wineprefix"
export WINEARCH=win64
export WINEDEBUG=-all

command -v wine >/dev/null 2>&1 || {
    echo "Wine is not installed. Run: sudo apt install wine64"
    exit 1
}

echo "[1/5] Preparing Wine prefix (first run can take a minute)..."
mkdir -p "$WINEPREFIX"
wineboot -u >/dev/null 2>&1 || true

INSTALLER=".tools/python-$PYVER-amd64.exe"
mkdir -p .tools
if [ ! -f "$INSTALLER" ]; then
    echo "[2/5] Downloading the official Windows Python $PYVER installer..."
    URL="https://www.python.org/ftp/python/$PYVER/python-$PYVER-amd64.exe"
    if command -v curl >/dev/null 2>&1; then
        curl -L -o "$INSTALLER" "$URL"
    else
        wget -O "$INSTALLER" "$URL"
    fi
else
    echo "[2/5] Windows Python installer already downloaded."
fi

echo "[3/5] Installing Python inside Wine (silent, with pip + tkinter)..."
wine "$INSTALLER" /quiet InstallAllUsers=0 PrependPath=1 Include_tcltk=1 Include_pip=1

WINE_PY="wine $WINEPREFIX/drive_c/users/$USER/AppData/Local/Programs/Python/Python${PYVER%.*}/python.exe"
# Fallback: locate python.exe automatically if the path above doesn't match.
WINE_PY_EXE="$(find "$WINEPREFIX/drive_c" -iname "python.exe" -path "*Python3*" 2>/dev/null | head -n1)"
if [ -n "$WINE_PY_EXE" ]; then
    WINE_PY="wine $WINE_PY_EXE"
fi

echo "[4/5] Installing PyInstaller inside Wine..."
$WINE_PY -m pip install --upgrade pip pyinstaller

echo "[5/5] Building Calyx-Installer.exe ..."
$WINE_PY -m PyInstaller --noconfirm --clean --onefile --windowed \
    --name "$APP" \
    --add-data "calyx.py;." \
    --add-data "LICENSE;." \
    --add-data "assets;assets" \
    --add-data "examples;examples" \
    installer.py

echo
echo "Done: dist/$APP.exe"
echo "Copy it to a Windows machine and double-click it to launch the installer."
echo "(You can sanity-check it under Linux with: wine dist/$APP.exe)"
