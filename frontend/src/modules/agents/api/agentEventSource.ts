import type { AgentEvent } from '../model/types'
import { parseAgentEvent } from '../model/events'

export const RECONNECT_MIN_MS = 500
export const RECONNECT_MAX_MS = 5000
export type AgentEventConnection = Pick<EventSource, 'onopen' | 'onmessage' | 'onerror' | 'close'>
export interface AgentEventTransport {
  open(
    sessionId: string,
    after: number,
    handlers: {
      event: (event: AgentEvent) => void
      state: (state: 'connected' | 'reconnecting') => void
      error: (cause: unknown) => void
    },
  ): void
  accept(cursor: number): void
  close(): void
}

export function createAgentEventSource(
  sourceFactory: (url: string) => AgentEventConnection = (url) => new EventSource(url),
  clock: Pick<typeof globalThis, 'setTimeout' | 'clearTimeout'> = globalThis,
): AgentEventTransport {
  let source: AgentEventConnection | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let generation = 0
  let attempts = 0
  let cursor = 0

  function release() {
    source?.close()
    source = undefined
    if (timer !== undefined) clock.clearTimeout(timer)
    timer = undefined
  }
  function close() {
    generation++
    release()
  }
  function open(
    sessionId: string,
    after: number,
    handlers: Parameters<AgentEventTransport['open']>[2],
  ) {
    close()
    attempts = 0
    cursor = after
    const version = generation
    function connect() {
      if (version !== generation || source) return
      const connection = sourceFactory(
        `/api/channels/web/sessions/${encodeURIComponent(sessionId)}/events?after=${cursor}`,
      )
      source = connection
      connection.onopen = () => {
        if (version !== generation || source !== connection) return
        attempts = 0
        handlers.state('connected')
      }
      connection.onmessage = (message) => {
        if (version !== generation || source !== connection) return
        try {
          handlers.event(parseAgentEvent(JSON.parse(message.data)))
        } catch (cause) {
          close()
          handlers.error(cause)
        }
      }
      connection.onerror = () => {
        if (version !== generation || source !== connection) return
        release()
        handlers.state('reconnecting')
        timer = clock.setTimeout(
          connect,
          Math.min(RECONNECT_MIN_MS * 2 ** attempts++, RECONNECT_MAX_MS),
        )
      }
    }
    connect()
  }
  return {
    open,
    accept: (value) => {
      cursor = value
    },
    close,
  }
}
