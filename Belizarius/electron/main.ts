
import { app, BrowserWindow, ipcMain } from 'electron'
import { spawn, type ChildProcess } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import type {
  ActivityEvent,
  BelizariusStatus,
  VisibilityMode,
} from '../src/shared-types'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

process.env.APP_ROOT = path.join(__dirname, '..')

export const VITE_DEV_SERVER_URL = process.env['VITE_DEV_SERVER_URL']
export const MAIN_DIST = path.join(process.env.APP_ROOT, 'dist-electron')
export const RENDERER_DIST = path.join(process.env.APP_ROOT, 'dist')

process.env.VITE_PUBLIC = VITE_DEV_SERVER_URL
  ? path.join(process.env.APP_ROOT, 'public')
  : RENDERER_DIST

let win: BrowserWindow | null = null
let listenerProcess: ChildProcess | null = null
let conversationProcess: ChildProcess | null = null

let quitting = false
let conversationRequested = false
let visibilityMode: VisibilityMode = 'TRANSPARENCY'
let pendingWakePhrase: string | null = null
let nextActivityId = 1

function send(channel: string, ...args: unknown[]) {
  if (win && !win.isDestroyed() && !win.webContents.isDestroyed()) {
    win.webContents.send(channel, ...args)
  }
}

function setStatus(status: BelizariusStatus) {
  send('voice:status', status)
}

function activity(
  action: string,
  status: ActivityEvent['status'],
  details?: string,
) {
  const event: ActivityEvent = {
    id: String(nextActivityId++),
    action,
    status,
    details,
    timestamp: Date.now(),
  }

  send('activity:event', event)
}

function createWindow() {
  if (win && !win.isDestroyed()) {
    win.show()
    return
  }

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
    send('main-process-message', new Date().toLocaleString())

    if (pendingWakePhrase) {
      send('voice:wake-word', pendingWakePhrase)
      pendingWakePhrase = null
    }
  })

  if (VITE_DEV_SERVER_URL) {
    void win.loadURL(VITE_DEV_SERVER_URL)
  } else {
    void win.loadFile(path.join(RENDERER_DIST, 'index.html'))
  }

  win.on('closed', () => {
    win = null
  })
}

function pythonPaths() {
  const root = app.getAppPath()

  return {
    python: path.join(
      root,
      'voice_engine',
      '.venv',
      'Scripts',
      'python.exe',
    ),
    listener: path.join(root, 'voice_engine', 'wake_sherpa.py'),
    conversation: path.join(root, 'voice_engine', 'conversation.py'),
    root,
  }
}

function startListener() {
  if (quitting || conversationRequested || conversationProcess) return
  if (listenerProcess) return

  const paths = pythonPaths()
  console.log('[Belizarius] Starting wake listener:', paths.listener)

  let child: ChildProcess

  try {
    child = spawn(paths.python, ['-u', paths.listener], {
      cwd: paths.root,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
  } catch (error) {
    console.error('[Belizarius] Could not start wake listener:', error)
    setStatus('ERROR')
    return
  }

  listenerProcess = child
  let buffer = ''

  child.stdout?.on('data', (data: Buffer) => {
    buffer += data.toString()
    const lines = buffer.split(/\r?\n/)
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      if (!line.trim()) continue

      if (line.startsWith('WAKE_WORD:')) {
        const phrase = line.slice('WAKE_WORD:'.length).trim()

        if (conversationRequested || conversationProcess || quitting) continue

        console.log('[Belizarius] Wake word detected:', phrase)
        conversationRequested = true
        pendingWakePhrase = phrase
        createWindow()
        setStatus('THINKING')

        // Let the listener process exit before opening the same microphone.
        stopListener()
      } else {
        console.log('[Wake listener]', line)
      }
    }
  })

  child.stderr?.on('data', (data: Buffer) => {
    console.error('[Wake listener]', data.toString())
  })

  child.on('error', (error) => {
    console.error('[Belizarius] Wake listener failed:', error)
    if (listenerProcess === child) listenerProcess = null
    setStatus('ERROR')
  })

  child.on('exit', (code) => {
    console.log('[Belizarius] Wake listener exit code:', code)

    if (listenerProcess === child) listenerProcess = null

    if (quitting) return

    if (conversationRequested && !conversationProcess) {
      startConversation()
    } else if (!conversationRequested) {
      // Retry a listener that stopped unexpectedly.
      setTimeout(startListener, 1000)
    }
  })
}

function stopListener() {
  if (listenerProcess && listenerProcess.exitCode === null) {
    listenerProcess.kill()
  }
}

function startConversation() {
  if (quitting || conversationProcess) return

  const paths = pythonPaths()
  console.log('[Belizarius] Starting Gemini conversation:', paths.conversation)
  activity('Voice conversation', 'started')
  setStatus('THINKING')

  let child: ChildProcess

  try {
    child = spawn(paths.python, ['-u', paths.conversation], {
      cwd: paths.root,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
  } catch (error) {
    console.error('[Belizarius] Could not start conversation:', error)
    conversationRequested = false
    setStatus('ERROR')
    activity('Voice conversation', 'failed', String(error))
    startListener()
    return
  }

  conversationProcess = child
  let buffer = ''

  child.stdout?.on('data', (data: Buffer) => {
    buffer += data.toString()
    const lines = buffer.split(/\r?\n/)
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed) continue

      console.log('[Conversation]', trimmed)

      if (trimmed === 'CONNECTING_TO_GEMINI') {
        setStatus('THINKING')
      } else if (trimmed === 'GEMINI_CONNECTED' ||
                 trimmed.startsWith('MICROPHONE_READY')) {
        setStatus('LISTENING')
      } else if (trimmed.startsWith('YOU SAID:')) {
        send('voice:input', trimmed.slice('YOU SAID:'.length).trim())
        setStatus('THINKING')
      } else if (trimmed.startsWith('BELIZARIUS:')) {
        send('voice:output', trimmed.slice('BELIZARIUS:'.length).trim())
        setStatus('SPEAKING')
      } else if (trimmed === 'TURN_COMPLETE') {
        setStatus('LISTENING')
      } else if (trimmed.startsWith('ERROR:')) {
        setStatus('ERROR')
        activity('Voice conversation', 'failed', trimmed.slice(6).trim())
      }
    }
  })

  child.stderr?.on('data', (data: Buffer) => {
    console.error('[Conversation error]', data.toString())
  })

  child.on('error', (error) => {
    console.error('[Belizarius] Conversation process failed:', error)
    setStatus('ERROR')
    activity('Voice conversation', 'failed', String(error))
  })

  child.on('exit', (code) => {
    console.log('[Belizarius] Conversation exit code:', code)

    if (conversationProcess === child) conversationProcess = null

    if (quitting) return

    if (code === 0) {
      activity('Voice conversation', 'completed')
      setStatus('IDLE')
    } else {
      activity('Voice conversation', 'failed', `Process exited with code ${code}`)
      setStatus('ERROR')
    }

    conversationRequested = false
    pendingWakePhrase = null
    startListener()
  })
}

ipcMain.handle('ui:set-visibility-mode', (_event, mode: VisibilityMode) => {
  if (mode !== 'STEALTH' && mode !== 'TRANSPARENCY') {
    throw new Error('Invalid visibility mode')
  }

  visibilityMode = mode

  if (win && !win.isDestroyed()) {
    if (mode === 'STEALTH') {
      win.setOpacity(0.85)
    } else {
      win.setOpacity(1)
    }
  }

  console.log('[Belizarius] Visibility mode:', visibilityMode)
})

ipcMain.handle('voice:stop-conversation', () => {
  conversationRequested = false

  if (conversationProcess && conversationProcess.exitCode === null) {
    conversationProcess.kill()
  } else if (!listenerProcess) {
    startListener()
  }
})

app.whenReady().then(() => {
  console.log('[Belizarius] Electron main process is running')
  startListener()
})

app.on('before-quit', () => {
  quitting = true
  stopListener()

  if (conversationProcess && conversationProcess.exitCode === null) {
    conversationProcess.kill()
  }
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
