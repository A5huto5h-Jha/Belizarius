
import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  onWakeWord: (callback: (phrase: string) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, phrase: string) => {
      callback(phrase)
    }

    ipcRenderer.on('voice:wake-word', listener)

    return () => {
      ipcRenderer.removeListener('voice:wake-word', listener)
    }
  },

  onMainProcessMessage: (callback: (message: string) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, message: string) => {
      callback(message)
    }

    ipcRenderer.on('main-process-message', listener)

    return () => {
      ipcRenderer.removeListener('main-process-message', listener)
    }
  },
})
