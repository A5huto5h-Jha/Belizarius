import { app, BrowserWindow } from 'electron'
import { spawn, type ChildProcess } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

process.env.APP_ROOT = path.join(__dirname, '..')

export const VITE_DEV_SERVER_URL = process.env['VITE_DEV_SERVER_URL']
export const MAIN_DIST = path.join(process.env.APP_ROOT, 'dist-electron')
export const RENDERER_DIST = path.join(process.env.APP_ROOT, 'dist')

process.env.VITE_PUBLIC = VITE_DEV_SERVER_URL
  ? path.join(process.env.APP_ROOT, 'public')
  : RENDERER_DIST

let win: BrowserWindow | null = null
let voiceProcess: ChildProcess | null = null

function createWindow() {
  win = new BrowserWindow({
    width: 300,
    height: 300,
    frame: false,
    transparent: true,
    backgroundColor: '#00000000',
    resizable: false,
    hasShadow: false,
    alwaysOnTop: true,
    icon: path.join(process.env.VITE_PUBLIC!, 'electron-vite.svg'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.mjs'),
    },
  })

  win.webContents.on('did-finish-load', () => {
    win?.webContents.send('main-process-message', new Date().toLocaleString())
  })

  if (VITE_DEV_SERVER_URL) {
    win.loadURL(VITE_DEV_SERVER_URL)
  } else {
    win.loadFile(path.join(RENDERER_DIST, 'index.html'))
  }

  win.on('closed', () => {
    win = null
  })
}

function startVoiceListener() {
  console.log('[Belizarius] Attempting to start Python...')
  console.log('[Belizarius] App path:', app.getAppPath())
  if (voiceProcess && voiceProcess.exitCode === null && !voiceProcess.killed) {
    return
  }

  // Development path. Packaging needs a separate Python/model deployment setup.
  const projectRoot = app.getAppPath()
  const pythonPath = path.join(
    projectRoot, 'voice_engine', '.venv', 'Scripts', 'python.exe'
  )
  const listenerPath = path.join(
    projectRoot, 'voice_engine', 'wake_sherpa.py'
  )
  console.log('[Belizarius] Python path:', pythonPath)
  console.log('[Belizarius] Listener path:', listenerPath)
  voiceProcess = spawn(pythonPath, ['-u', listenerPath], {
    cwd: projectRoot,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  let stdoutBuffer = ''

  voiceProcess.stdout?.on('data', (data: Buffer) => {
    stdoutBuffer += data.toString()
    const lines = stdoutBuffer.split(/\r?\n/)
    stdoutBuffer = lines.pop() ?? ''

    for (const line of lines) {
      if (line.startsWith('WAKE_WORD:')) {
        createWindow()
        const phrase = line.slice('WAKE_WORD:'.length).trim()
        win?.webContents.send('voice:wake-word', phrase)
      } else if (line.trim()) {
        console.log('[Voice engine]', line)
      }
    }
  })

  voiceProcess.stderr?.on('data', (data: Buffer) => {
    console.error('[Voice engine]', data.toString())
  })

  voiceProcess.on('error', (error) => {
    console.error('[Voice engine failed to start]', error)
  })

  voiceProcess.on('exit', (code) => {
    console.log('[Belizarius] Python exit code:', code)
    console.log('[Voice engine exited]', code)
    voiceProcess = null
  })
}

function stopVoiceListener() {
  if (voiceProcess) {
    voiceProcess.kill()
    voiceProcess = null
  }
}

app.whenReady().then(() => {
  console.log('[Belizarius] Electron main process is running')
  
  startVoiceListener()
})

app.on('before-quit', stopVoiceListener)

app.on('window-all-closed', () => {
  // Keep normal Electron platform behavior; Windows closes the app.
  if (process.platform !== 'darwin') app.quit()
})