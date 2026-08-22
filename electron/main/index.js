import { app, BrowserWindow } from 'electron'
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import http from 'node:http'
import { assertBundledPluginRuntime } from './desktopRuntime.js'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

let backendProcess = null
let backendDebugPidPath = null

const BACKEND_HOST = '127.0.0.1'
const BACKEND_PORT = 18765
const API_BASE = `http://${BACKEND_HOST}:${BACKEND_PORT}`
// 调试开关：设 WAVEFLOW_DESKTOP_DEBUG=1，或启动 app 时传 --waveflow-debug。
// 打开后前端允许 F12 Console，后端会在可见终端窗口里启动。
const DESKTOP_DEBUG =
  process.env.WAVEFLOW_DESKTOP_DEBUG === '1' || process.argv.includes('--waveflow-debug')

function getBackendExecutableName() {
  return process.platform === 'win32' ? 'waveflow-backend.exe' : 'waveflow-backend'
}

function getBackendPath() {
  const executableName = getBackendExecutableName()

  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'backend', executableName)
  }

  return path.join(app.getAppPath(), 'backend_dist', executableName)
}

function getFrontendIndexPath() {
  if (app.isPackaged) {
    return path.join(app.getAppPath(), 'frontend', 'dist', 'index.html')
  }

  return path.join(process.cwd(), 'frontend', 'dist', 'index.html')
}

function getBackendArgs() {
  return [
    '--host',
    BACKEND_HOST,
    '--port',
    String(BACKEND_PORT),
    '--data-dir',
    app.getPath('userData'),
  ]
}

function quoteShellArg(value) {
  return `'${String(value).replaceAll("'", "'\\''")}'`
}

function startBackendInDebugTerminal(backendPath, backendArgs) {
  if (process.platform === 'win32') {
    const logFd = fs.openSync(path.join(app.getPath('userData'), 'backend.log'), 'a')
    try {
      return spawn(backendPath, backendArgs, {
        windowsHide: false,
        stdio: ['ignore', 'ignore', logFd],
      })
    } finally {
      fs.closeSync(logFd)
    }
  }

  if (process.platform === 'darwin') {
    backendDebugPidPath = path.join(app.getPath('userData'), 'backend-debug.pid')
    const command = [
      'rm',
      '-f',
      quoteShellArg(backendDebugPidPath),
      '&&',
      'echo',
      '$$',
      '>',
      quoteShellArg(backendDebugPidPath),
      '&&',
      'exec',
      [backendPath, ...backendArgs].map(quoteShellArg).join(' '),
    ].join(' ')
    const script = `tell application "Terminal" to do script ${JSON.stringify(command)}`

    return spawn('osascript', ['-e', script], {
      stdio: ['ignore', 'ignore', fs.openSync(app.getPath('userData') + '/backend.log', 'w')],
    })
  }

  return spawn(backendPath, backendArgs, {
    stdio: 'inherit',
  })
}

function startBackend() {
  const backendPath = getBackendPath()
  assertBundledPluginRuntime(backendPath)
  const backendArgs = getBackendArgs()

  if (DESKTOP_DEBUG) {
    backendProcess = startBackendInDebugTerminal(backendPath, backendArgs)
  } else {
    backendProcess = spawn(backendPath, backendArgs, {
      windowsHide: true,
      stdio: ['ignore', 'ignore', fs.openSync(app.getPath('userData') + '/backend.log', 'w')],
    })
  }

  backendProcess.on('exit', (code) => {
    console.log('[WaveFlow 后端退出]', code)
  })
}

function stopBackend() {
  if (DESKTOP_DEBUG && process.platform === 'darwin' && backendDebugPidPath) {
    try {
      const pid = Number(fs.readFileSync(backendDebugPidPath, 'utf8').trim())
      if (pid) {
        process.kill(pid)
      }
      fs.rmSync(backendDebugPidPath, { force: true })
    } catch {
      // 调试终端可能已被手动关闭；这里静默清理即可。
    }
  }

  if (backendProcess) {
    backendProcess.kill()
    backendProcess = null
  }
}

function waitForBackend(timeoutMs = 12000) {
  const startedAt = Date.now()

  return new Promise((resolve, reject) => {
    const check = () => {
      const req = http.get(`${API_BASE}/health`, () => {
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
      height: 28,
    },
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.mjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      devTools: DESKTOP_DEBUG,
    },
  })

  if (DESKTOP_DEBUG) {
    win.webContents.on('before-input-event', (event, input) => {
      if (input.type === 'keyDown' && input.key === 'F12') {
        win.webContents.toggleDevTools()
      }
    })
  }

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
  stopBackend()
})

app.on('window-all-closed', () => {
  app.quit()
})
