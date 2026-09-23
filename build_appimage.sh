#!/bin/sh
# ============================================================
#  Calyx - build a Linux AppImage
#  Produces Calyx-Installer-x86_64.AppImage : a single portable
#  file, executable on most Linux distros without installing
#  anything (it embeds its own Python via PyInstaller).
#  Run this on Linux. Needs internet access once, to download
#  appimagetool (cached locally afterwards).
# ============================================================
set -e
cd "$(dirname "$0")"

APP=Calyx-Installer
ARCH="$(uname -m)"

PY=python3
command -v "$PY" >/dev/null 2>&1 || { echo "python3 was not found. Install Python 3 then retry."; exit 1; }

echo "[1/5] Creating build environment (.buildenv) and installing PyInstaller..."
"$PY" -m venv .buildenv || {
    echo "Failed to create a venv. On Debian/Ubuntu, run: sudo apt install python3-venv"
    exit 1
}
.buildenv/bin/python -m pip install --upgrade pip pyinstaller

.buildenv/bin/python -c "import tkinter" 2>/dev/null || {
    echo "tkinter is missing. Install it then retry: sudo apt install python3-tk"
    exit 1
}

echo "[2/5] Building the app with PyInstaller (--onedir)..."
.buildenv/bin/python -m PyInstaller --noconfirm --clean --onedir --windowed \
    --name "$APP" \
    --add-data "calyx.py:." \
    --add-data "LICENSE:." \
    --add-data "assets:assets" \
    --add-data "examples:examples" \
    installer.py

echo "[3/5] Assembling the AppDir..."
rm -rf "$APP.AppDir"
mkdir -p "$APP.AppDir/usr/bin"
cp -r "dist/$APP/"* "$APP.AppDir/usr/bin/"

# Icon: reuse the linux asset, converted to a top-level PNG icon.
cp "assets/linux.png" "$APP.AppDir/$APP.png"

# Desktop entry (required by AppImage).
cat > "$APP.AppDir/$APP.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Calyx Installer
Exec=$APP
Icon=$APP
Categories=Development;
Terminal=false
EOF

# AppRun: entry point launched when the AppImage is executed.
cat > "$APP.AppDir/AppRun" <<EOF
#!/bin/sh
HERE="\$(dirname "\$(readlink -f "\$0")")"
exec "\$HERE/usr/bin/$APP" "\$@"
EOF
chmod +x "$APP.AppDir/AppRun"

echo "[4/5] Fetching appimagetool (cached in .tools/ after first run)..."
mkdir -p .tools
TOOL=".tools/appimagetool-$ARCH.AppImage"
if [ ! -x "$TOOL" ]; then
    URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
    if command -v curl >/dev/null 2>&1; then
        curl -L -o "$TOOL" "$URL"
    else
        wget -O "$TOOL" "$URL"
    fi
    chmod +x "$TOOL"
fi

echo "[5/5] Building the AppImage..."
ARCH="$ARCH" "$TOOL" "$APP.AppDir" "$APP-$ARCH.AppImage"

echo
echo "Done: $APP-$ARCH.AppImage"
echo "Make it executable if needed: chmod +x $APP-$ARCH.AppImage"
echo "Then double-click it (or run ./$APP-$ARCH.AppImage) to launch the installer."
