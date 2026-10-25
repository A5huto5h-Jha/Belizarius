
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
    }
  }
}
