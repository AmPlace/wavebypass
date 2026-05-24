$ErrorActionPreference = "Stop"

Write-Host "== Build frontend =="
cd frontend
npm install
npm run build -- --mode desktop
cd ..

Write-Host "== Build backend =="
cd backend

if (!(Test-Path ".venv")) {
  python -m venv .venv
}

.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\pip install pyinstaller

.\.venv\Scripts\pyinstaller.exe `
  --clean `
  --onefile `
  --add-data "config;config" `
  --name waveflow-backend `
  desktop_entry.py

cd ..

Write-Host "== Copy backend exe =="
if (!(Test-Path "backend_dist")) {
  New-Item -ItemType Directory backend_dist | Out-Null
}

Copy-Item backend\dist\waveflow-backend.exe backend_dist\waveflow-backend.exe -Force

Write-Host "== Install desktop deps =="
npm install

Write-Host "== Build Electron main/preload =="
npm run build:electron

Write-Host "== Build Windows installer =="
npx electron-builder --win

Write-Host "== Done =="
