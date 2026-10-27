
import type {
  ActivityEvent,
  BelizariusStatus,
  VisibilityMode,
} from './shared-types'

export {}

declare global {
  interface Window {
    electronAPI: {
      onWakeWord: (
        callback: (phrase: string) => void
      ) => () => void

      onMainProcessMessage: (
        callback: (message: string) => void
      ) => () => void

      onVoiceStatus: (
        callback: (status: BelizariusStatus) => void
      ) => () => void

      onVoiceOutput: (
        callback: (text: string) => void
      ) => () => void
      
      onVoiceInput: (
        callback: (text: string) => void
      ) => () => void

      onActivity: (
        callback: (event: ActivityEvent) => void
      ) => () => void

      setVisibilityMode: (
        mode: VisibilityMode
      ) => Promise<void>

      stopConversation: () => Promise<void>
    }
  }
}
