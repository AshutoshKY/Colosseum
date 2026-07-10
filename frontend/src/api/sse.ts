import type { ProgressEvent } from '../types'

export interface EventSubscription { close(): void }

export function subscribeToRun(id: string, onEvent: (event: ProgressEvent) => void, onFallback: () => void, eventSource: typeof EventSource = EventSource): EventSubscription {
  const source = new eventSource(`/api/runs/${id}/events`)
  const receive = (message: MessageEvent) => { try { onEvent(JSON.parse(message.data) as ProgressEvent) } catch { /* heartbeat/non-JSON */ } }
  source.onmessage = receive
  source.addEventListener('cell', receive as EventListener)
  source.addEventListener('run', receive as EventListener)
  source.onerror = () => { source.close(); onFallback() }
  return { close: () => source.close() }
}
