import { app, BrowserWindow } from 'electron'
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import http from 'node:http'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

let backendProcess = null

const BACKEND_HOST = '127.0.0.1'
const BACKEND_PORT = 18765
const API_BASE = `http://${BACKEND_HOST}:${BACKEND_PORT}`

function getBackendExecutableName() {
  return process.platform === 'win32' ? 'waveflow-backend.exe' : 'waveflow-backend'
}

function getBackendPath() {
  const executableName = getBackendExecutableName()

  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'backend', executableName)
  }

  return path.join(process.cwd(), 'backend_dist', executableName)
}

function getFrontendIndexPath() {
  if (app.isPackaged) {
    return path.join(app.getAppPath(), 'frontend', 'dist', 'index.html')
  }

  return path.join(process.cwd(), 'frontend', 'dist', 'index.html')
}

function startBackend() {
  const backendPath = getBackendPath()

  backendProcess = spawn(
    backendPath,
    [
      '--host',
      BACKEND_HOST,
      '--port',
      String(BACKEND_PORT),
      '--data-dir',
      app.getPath('userData'),
    ],
    {
      windowsHide: true,
      stdio: 'ignore',
    },
  )

  backendProcess.on('exit', (code) => {
    console.log('[WaveFlow 后端退出]', code)
  })
}

function waitForBackend(timeoutMs = 12000) {
  const startedAt = Date.now()

  return new Promise((resolve, reject) => {
    const check = () => {
      const req = http.get(`${API_BASE}/docs`, () => {
        resolve()
      })

      req.on('error', () => {
        if (Date.now() - startedAt > timeoutMs) {
          reject(new Error('后端启动超时'))
          return
        }

        setTimeout(check, 300)
      })

      req.setTimeout(1000, () => {
        req.destroy()
      })
    }

    check()
  })
}

async function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1000,
    minHeight: 680,
    title: 'WaveFlow',
    backgroundColor: '#f8f8f7',
    titleBarStyle: 'hidden',
    titleBarOverlay: {
      color: '#f8f8f7',
      symbolColor: '#111827',
      height: 36,
    },
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.mjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  })

  win.once('ready-to-show', () => {
    win.show()
  })

  await win.loadFile(getFrontendIndexPath())
}

app.whenReady().then(async () => {
  startBackend()

  try {
    await waitForBackend()
  } catch (error) {
    console.error('[WaveFlow 后端启动失败]', error)
  }

  await createWindow()
})

app.on('before-quit', () => {
  if (backendProcess) {
    backendProcess.kill()
    backendProcess = null
  }
})

app.on('window-all-closed', () => {
  app.quit()
})
