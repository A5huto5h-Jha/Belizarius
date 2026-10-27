
export type BelizariusStatus =
  | 'IDLE'
  | 'LISTENING'
  | 'THINKING'
  | 'SPEAKING'
  | 'ERROR'

export type VisibilityMode = 'STEALTH' | 'TRANSPARENCY'

export type ActivityEvent = {
  id: string
  action: string
  status: 'started' | 'completed' | 'failed'
  details?: string
  timestamp: number
}
