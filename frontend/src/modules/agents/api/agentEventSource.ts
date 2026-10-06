import { createEventSource, type EventConnection } from '@/shared/api/eventSource'
import type { AgentEvent } from '../model/public'
import { parseAgentEvent } from '../model/runtime/events'

export type AgentEventConnection = EventConnection
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
  const connection = createEventSource(sourceFactory, clock)
  let cursor = 0
  return {
    open(sessionId, after, handlers) {
      cursor = after
      connection.open({
        url: () => `/api/channels/web/sessions/${encodeURIComponent(sessionId)}/events?after=${cursor}`,
        parse: parseAgentEvent,
        data: handlers.event,
        state: handlers.state,
        error: handlers.error,
      })
    },
    accept(value) {
      cursor = value
    },
    close: connection.close,
  }
}
