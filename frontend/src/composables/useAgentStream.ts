import { onScopeDispose, ref, shallowRef } from 'vue'
import { agentsApi, type AgentEvent } from '@/api/agents'
import { errorMessage } from '@/api/client'

const terminal = new Set(['turn.completed', 'turn.failed', 'turn.cancelled', 'turn.interrupted'])
export function mergeAgentEvents(current: AgentEvent[], incoming: AgentEvent[]): AgentEvent[] {
  const seen = new Set(current.map((event) => `${event.session_id}:${event.id}`))
  return [
    ...current,
    ...incoming.filter((event) => {
      const key = `${event.session_id}:${event.id}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    }),
  ]
}
export function useAgentStream(onEvent: (event: AgentEvent) => void) {
  const events = shallowRef<AgentEvent[]>([])
  const state = ref<'loading' | 'connected' | 'reconnecting' | 'closed'>('closed')
  const error = ref('')
  let sessionId = ''
  let cursor = 0
  let source: EventSource | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let controller: AbortController | undefined
  let generation = 0
  let attempts = 0
  let liveTurn: string | null = null

  function disconnect() {
    source?.close()
    source = undefined
    clearTimeout(timer)
    timer = undefined
  }
  function connect() {
    if (!sessionId || source) return
    const version = generation
    const connection = new EventSource(
      `/api/agents/sessions/${encodeURIComponent(sessionId)}/events?after=${cursor}`,
    )
    source = connection
    connection.onopen = () => {
      if (version === generation && source === connection) {
        state.value = 'connected'
        attempts = 0
      }
    }
    connection.onmessage = (message) => {
      if (version !== generation || source !== connection) return
      let event: AgentEvent
      try {
        event = JSON.parse(message.data) as AgentEvent
        if (!Number.isSafeInteger(event.id) || event.session_id !== sessionId || !event.data)
          throw new Error('事件信封无效')
      } catch (cause) {
        error.value = errorMessage(cause)
        disconnect()
        state.value = 'closed'
        return
      }
      if (event.id <= cursor) return
      cursor = event.id
      events.value = mergeAgentEvents(events.value, [event])
      if (!liveTurn && event.type === 'turn.started') liveTurn = event.turn_id
      if (!event.turn_id || event.turn_id === liveTurn) onEvent(event)
      if (terminal.has(event.type) && event.turn_id === liveTurn) {
        disconnect()
        state.value = 'closed'
      }
    }
    connection.onerror = () => {
      if (version !== generation || source !== connection) return
      disconnect()
      state.value = 'reconnecting'
      // Durable IDs provide recovery; retry timing only controls UI/network load.
      timer = setTimeout(connect, Math.min(500 * 2 ** attempts++, 5000))
    }
  }
  async function select(id: string) {
    generation++
    disconnect()
    controller?.abort()
    controller = new AbortController()
    const version = generation
    sessionId = id
    cursor = 0
    liveTurn = null
    events.value = []
    error.value = ''
    state.value = 'loading'
    try {
      const history = await agentsApi.history(id, controller.signal)
      if (version !== generation) return
      events.value = mergeAgentEvents([], history)
      cursor = Math.max(
        0,
        ...history.filter((event) => event.session_id === id).map((event) => event.id),
      )
      const session = await agentsApi.get(id, controller.signal)
      if (version !== generation) return
      liveTurn = session.turn_id
      // A completed history has no live tail until the next accepted turn.
      // Recheck after history to avoid confusing an old terminal with a new turn.
      const latestTerminal = [...history]
        .reverse()
        .find((event) => event.session_id === id && terminal.has(event.type))
      if (session.status !== 'running' && latestTerminal?.turn_id === session.turn_id)
        state.value = 'closed'
      else connect()
      return session
    } catch (cause) {
      if (version === generation) {
        error.value = errorMessage(cause)
        state.value = 'closed'
      }
    }
  }
  function resume(turnId: string) {
    generation++
    disconnect()
    controller?.abort()
    liveTurn = turnId
    error.value = ''
    connect()
  }
  function clear() {
    generation++
    disconnect()
    controller?.abort()
    sessionId = ''
    events.value = []
    state.value = 'closed'
  }
  onScopeDispose(() => {
    generation++
    disconnect()
    controller?.abort()
  })
  return { events, state, error, select, resume, clear }
}
