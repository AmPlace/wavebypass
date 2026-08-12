#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "== Build frontend =="
cd frontend
npm install
npm run build -- --mode desktop
cd "$ROOT_DIR"

echo "== Build backend =="
cd backend

# Keep PyInstaller's writable cache in the build workspace's temp area rather
# than relying on a pre-existing user cache with unknown ownership.
export PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-${TMPDIR:-/tmp}/waveflow-pyinstaller-config}"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

.venv/bin/pip install -r requirements.txt
.venv/bin/pip install pyinstaller

.venv/bin/pyinstaller \
  --clean \
  --noconfirm \
  --onedir \
  --hidden-import adapters.17live --collect-data zhconv \
  --add-data "config:config" --add-data "official_plugins:official_plugins" \
  --name waveflow-backend \
  desktop_entry.py

cd "$ROOT_DIR"

echo "== Copy backend binary =="
rm -rf backend_dist
mkdir -p backend_dist
cp -a backend/dist/waveflow-backend/. backend_dist/
chmod +x backend_dist/waveflow-backend

echo "== Bundle controlled Python runtime =="
if [ -z "${WAVEFLOW_DESKTOP_PYTHON_RUNTIME_SOURCE:-}" ]; then
  echo "ERROR: set WAVEFLOW_DESKTOP_PYTHON_RUNTIME_SOURCE to a versioned macOS arm64 CPython 3.14 runtime root" >&2
  exit 1
fi
bash "$ROOT_DIR/scripts/stage-desktop-python-runtime.sh" \
  "$WAVEFLOW_DESKTOP_PYTHON_RUNTIME_SOURCE" \
  "$ROOT_DIR/backend_dist/python-runtime"

echo "== Bundle ffmpeg =="
FFMPEG_SRC=$(ls "$ROOT_DIR/ffmpeg/macos-arm64/ffmpeg" 2>/dev/null)
if [ -z "$FFMPEG_SRC" ]; then
  echo "  Downloading ffmpeg static build for macOS arm64..."
  bash "$ROOT_DIR/scripts/download-ffmpeg.sh" mac
  FFMPEG_SRC="$ROOT_DIR/ffmpeg/macos-arm64/ffmpeg"
fi
if [ -f "$FFMPEG_SRC" ]; then
  cp "$FFMPEG_SRC" "$ROOT_DIR/backend_dist/ffmpeg"
  chmod +x "$ROOT_DIR/backend_dist/ffmpeg"
  echo "  Bundled: $(file "$ROOT_DIR/backend_dist/ffmpeg" | cut -d: -f2-)"
else
  echo "  WARNING: ffmpeg not found, RTSP/HLS will NOT work"
fi

echo "== Install desktop deps =="
npm install

echo "== Build Electron main/preload =="
npm run build:electron

echo "== Build mac app =="
npx electron-builder --mac

echo "== Done =="
