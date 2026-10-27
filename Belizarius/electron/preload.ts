
import { contextBridge, ipcRenderer } from 'electron'
import type {
  ActivityEvent,
  BelizariusStatus,
  VisibilityMode,
} from '../src/shared-types'

contextBridge.exposeInMainWorld('electronAPI', {
  onWakeWord: (callback: (phrase: string) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, phrase: string) => {
      callback(phrase)
    }

    ipcRenderer.on('voice:wake-word', listener)
    return () => ipcRenderer.removeListener('voice:wake-word', listener)
  },

  onMainProcessMessage: (callback: (message: string) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, message: string) => {
      callback(message)
    }

    ipcRenderer.on('main-process-message', listener)
    return () => ipcRenderer.removeListener('main-process-message', listener)
  },

  onVoiceStatus: (callback: (status: BelizariusStatus) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, status: BelizariusStatus) => {
      callback(status)
    }

    ipcRenderer.on('voice:status', listener)
    return () => ipcRenderer.removeListener('voice:status', listener)
  },

  onVoiceOutput: (callback: (text: string) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, text: string) => {
      callback(text)
    }

    ipcRenderer.on('voice:output', listener)
    return () => ipcRenderer.removeListener('voice:output', listener)
  },
  
  onVoiceInput: (callback: (text: string) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, text: string) => {
      callback(text)
    }

    ipcRenderer.on('voice:input', listener)
    return () => ipcRenderer.removeListener('voice:input', listener)
  },

  onActivity: (callback: (event: ActivityEvent) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, event: ActivityEvent) => {
      callback(event)
    }

    ipcRenderer.on('activity:event', listener)
    return () => ipcRenderer.removeListener('activity:event', listener)
  },

  setVisibilityMode: (mode: VisibilityMode) =>
    ipcRenderer.invoke('ui:set-visibility-mode', mode),

  stopConversation: () =>
    ipcRenderer.invoke('voice:stop-conversation'),
})
