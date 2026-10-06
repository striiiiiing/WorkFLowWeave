import { onScopeDispose, ref, shallowRef } from 'vue'
import { useErrorFormatter } from '@/shared/async/errorFormatter'
import type { AgentsApi } from '../api/agentsApi'
import { createAgentEventSource, type AgentEventTransport } from '../api/agentEventSource'
import { mergeAgentEvents, parseAgentEvent, terminalTurnEvents } from '../model/runtime/events'
import { projectAgentSession } from '../model/runtime/sessionProjection'
import type { AgentEvent, AgentSession } from '../model/public'

type SessionApi = Pick<AgentsApi, 'history' | 'get'>

export function useAgentSession(
  api: SessionApi,
  transport: AgentEventTransport = createAgentEventSource(),
  onEvent?: (event: AgentEvent) => void,
) {
  const errorMessage = useErrorFormatter()
  const events = shallowRef<AgentEvent[]>([])
  const session = shallowRef<AgentSession>()
  const state = ref<'loading' | 'connected' | 'reconnecting' | 'closed'>('closed')
  const error = ref('')
  const cursor = ref(0)
  let generation = 0
  let controller: AbortController | undefined

  function stop() {
    generation++
    controller?.abort()
    controller = undefined
    transport.close()
  }

  function connect(id: string) {
    const version = generation
    transport.open(id, cursor.value, {
      event: (event) => {
        if (version !== generation) return
        if (event.session_id !== id) {
          stop()
          state.value = 'closed'
          error.value = 'Agent 事件会话不匹配'
          return
        }
        if (event.id <= cursor.value) return
        cursor.value = event.id
        transport.accept(cursor.value)
        events.value = mergeAgentEvents(events.value, [event])
        const current = session.value
        if (!current) return
        const activeTurn = current.turn_id
        session.value = projectAgentSession(current, event)
        if (
          !event.turn_id ||
          event.turn_id === activeTurn ||
          (event.type === 'turn.started' && session.value.turn_id === event.turn_id)
        )
          onEvent?.(event)
        if (terminalTurnEvents.has(event.type) && event.turn_id === activeTurn) {
          transport.close()
          state.value = 'closed'
        }
      },
      state: (next) => {
        if (version === generation) state.value = next
      },
      error: (cause) => {
        if (version !== generation) return
        error.value = errorMessage(cause)
        state.value = 'closed'
      },
    })
  }

  async function select(id: string): Promise<AgentSession | undefined> {
    stop()
    const version = generation
    const request = new AbortController()
    controller = request
    session.value = undefined
    events.value = []
    cursor.value = 0
    error.value = ''
    state.value = 'loading'
    try {
      const history = (await api.history(id, request.signal)).map(parseAgentEvent)
      if (version !== generation) return
      events.value = mergeAgentEvents([], history)
      cursor.value = Math.max(
        0,
        ...history.filter((event) => event.session_id === id).map((event) => event.id),
      )
      const current = await api.get(id, request.signal)
      if (version !== generation) return
      session.value = current
      controller = undefined
      const latestTerminal = [...history]
        .reverse()
        .find((event) => event.session_id === id && terminalTurnEvents.has(event.type))
      if (current.status !== 'running' && latestTerminal?.turn_id === current.turn_id)
        state.value = 'closed'
      else connect(id)
      return current
    } catch (cause) {
      if (version === generation) {
        controller = undefined
        error.value = errorMessage(cause)
        state.value = 'closed'
      }
    }
  }

  function resume(turnId: string) {
    const current = session.value
    if (!current) return
    stop()
    session.value = { ...current, status: 'running', turn_id: turnId }
    error.value = ''
    connect(current.session_id)
  }

  function clear() {
    stop()
    session.value = undefined
    events.value = []
    cursor.value = 0
    error.value = ''
    state.value = 'closed'
  }

  onScopeDispose(stop)
  return { events, session, state, error, cursor, select, resume, clear }
}
