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

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

.venv/bin/pip install -r requirements.txt
.venv/bin/pip install pyinstaller

.venv/bin/pyinstaller \
  --clean \
  --onefile \
  --add-data "config:config" \
  --name waveflow-backend \
  desktop_entry.py

cd "$ROOT_DIR"

echo "== Copy backend binary =="
rm -rf backend_dist
mkdir -p backend_dist
cp backend/dist/waveflow-backend backend_dist/waveflow-backend
chmod +x backend_dist/waveflow-backend

echo "== Install desktop deps =="
npm install

echo "== Build Electron main/preload =="
npm run build:electron

echo "== Build mac app =="
npx electron-builder --mac

echo "== Done =="
