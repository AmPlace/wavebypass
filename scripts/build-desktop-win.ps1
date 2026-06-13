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
  --onedir `
  --add-data "config;config" `
  --name waveflow-backend `
  desktop_entry.py

cd ..

Write-Host "== Copy backend exe =="
if (Test-Path "backend_dist") {
  Remove-Item backend_dist -Recurse -Force
}

New-Item -ItemType Directory backend_dist | Out-Null
Copy-Item backend\dist\waveflow-backend\* backend_dist\ -Recurse -Force

Write-Host "== Bundle ffmpeg =="
if (-not (Test-Path "ffmpeg\win-x64fmpeg.exe")) {
  Write-Host "  Downloading ffmpeg for Windows x64..."
  bash scripts/download-ffmpeg.sh win
}
if (Test-Path "ffmpeg\win-x64fmpeg.exe") {
  Copy-Item ffmpeg\win-x64fmpeg.exe backend_distfmpeg.exe -Force
  Write-Host "  Bundled ffmpeg.exe"
} else {
  Write-Host "  WARNING: ffmpeg.exe not found, will NOT be bundled"
}

Write-Host "== Install desktop deps =="
npm install

Write-Host "== Build Electron main/preload =="
npm run build:electron

Write-Host "== Build Windows installer =="
npx electron-builder --win

Write-Host "== Done =="
