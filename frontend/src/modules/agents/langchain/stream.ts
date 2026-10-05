import { computed, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { STREAM_CONTROLLER, useChannelEffect, useStream } from '@langchain/vue'
import { HumanMessage } from '@langchain/core/messages'
import { useErrorFormatter } from '@/shared/async/errorFormatter'
import type { AgentsApi } from '../api/agentsApi'
import { mergeAgentEvents, parseAgentEvent } from '../model/events'
import { projectAgentSession } from '../model/sessionProjection'
import type { AgentEvent, AgentSession, TurnAccepted } from '../model/types'
import { AgentServerAdapter } from './adapter'
import type { AgentStreamConnectionState, AgentStreamState } from './types'

const AGENT_CHANNELS = ['custom:agent'] as const

function agentEventFromProtocol(value: unknown): AgentEvent | undefined {
  if (!value || typeof value !== 'object' || !('method' in value) || value.method !== 'custom')
    return
  if (!('params' in value) || !value.params || typeof value.params !== 'object') return
  const params = value.params
  if (!('data' in params) || !params.data || typeof params.data !== 'object') return
  const data = params.data
  if (!('name' in data) || data.name !== 'agent' || !('payload' in data)) return
  return parseAgentEvent(data.payload)
}

export function useAgentSession(api: AgentsApi) {
  const formatError = useErrorFormatter()
  const session = shallowRef<AgentSession>()
  const history = shallowRef<AgentEvent[]>([])
  const liveEvents = shallowRef<AgentEvent[]>([])
  const state = ref<AgentStreamConnectionState>('closed')
  const error = ref('')
  let generation = 0
  let appliedThrough = 0

  const adapter = new AgentServerAdapter(api, {
    onConnectionState: (next) => {
      state.value = next
    },
  })
  const stream = useStream<AgentStreamState>({
    assistantId: 'logagent-agent',
    threadId: null,
    transport: adapter,
    initialValues: { messages: [] },
    optimistic: false,
  })
  useChannelEffect(stream, AGENT_CHANNELS, {
    replay: false,
    onEvent: (item) => {
      const event = agentEventFromProtocol(item)
      if (event) liveEvents.value = mergeAgentEvents(liveEvents.value, [event])
    },
  })
  const events = computed(() => mergeAgentEvents(history.value, liveEvents.value))
  const cursor = computed(() => {
    const id = session.value?.session_id
    if (!id) return 0
    return Math.max(
      0,
      ...events.value.filter((event) => event.session_id === id).map((event) => event.id),
    )
  })
  const errorMessage = computed(() => {
    if (error.value) return error.value
    return stream.error.value ? formatError(stream.error.value) : ''
  })

  watch(liveEvents, (incoming) => {
    const current = session.value
    if (!current) return
    for (const event of incoming) {
      if (event.session_id !== current.session_id || event.id <= appliedThrough) continue
      appliedThrough = event.id
      session.value = projectAgentSession(session.value ?? current, event)
    }
  })

  watch(events, (currentEvents) => {
    if (session.value) adapter.seedSession(session.value, currentEvents)
  })

  watch(
    () => stream.isThreadLoading.value,
    (loading) => {
      if (loading && session.value && state.value === 'closed') state.value = 'loading'
    },
  )

  function status(id: string): number {
    return Math.max(
      0,
      ...history.value.filter((event) => event.session_id === id).map((event) => event.id),
    )
  }

  async function select(id: string): Promise<AgentSession | undefined> {
    const version = ++generation
    error.value = ''
    if (session.value?.session_id !== id) {
      session.value = undefined
      history.value = []
      liveEvents.value = []
      appliedThrough = 0
      state.value = 'loading'
    }

    try {
      const [rawHistory, current] = await Promise.all([api.history(id), api.get(id)])
      if (version !== generation) return
      history.value = rawHistory.map(parseAgentEvent)
      appliedThrough = status(id)
      session.value = current
      adapter.seedSession(current, history.value)
      adapter.setThreadId(id)
      // The stream keeps a static null threadId; bind the selected session explicitly
      // so the SDK controller and transport use the same session.
      await stream[STREAM_CONTROLLER].hydrate(id)
      if (version !== generation) return
      if (current.status !== 'running' && state.value === 'loading') state.value = 'closed'
      return session.value
    } catch (cause) {
      if (version === generation) {
        error.value = formatError(cause)
        state.value = 'closed'
      }
    }
  }

  async function submit(
    id: string,
    text: string,
    requestId: string,
    append: boolean,
  ): Promise<TurnAccepted> {
    if (stream.threadId.value !== id) throw new Error('Agent session 已切换')
    if (append) return adapter.submit(id, text, requestId, true)
    return startRun(
      requestId,
      { messages: [new HumanMessage({ id: requestId, content: text })] },
      { agent_request_id: requestId, agent_action: 'message' },
    )
  }

  async function compact(id: string): Promise<TurnAccepted> {
    if (stream.threadId.value !== id) throw new Error('Agent session 已切换')
    const requestId = crypto.randomUUID()
    return startRun(
      requestId,
      { messages: [] },
      { agent_request_id: requestId, agent_action: 'compact' },
    )
  }

  function startRun(
    requestId: string,
    input: { messages: HumanMessage[] } | { messages: [] },
    metadata: { agent_request_id: string; agent_action: 'message' | 'compact' },
  ): Promise<TurnAccepted> {
    const accepted = adapter.waitForSubmission(requestId)
    void stream.submit(input, { metadata }).catch((cause) => {
      adapter.rejectSubmission(requestId, cause)
      error.value = formatError(cause)
    })
    return accepted
  }

  function resume(turnId: string) {
    if (!session.value) return
    session.value = { ...session.value, status: 'running', turn_id: turnId }
    error.value = ''
  }

  function clear() {
    generation++
    adapter.setThreadId('')
    void stream[STREAM_CONTROLLER].hydrate(null)
    session.value = undefined
    history.value = []
    liveEvents.value = []
    appliedThrough = 0
    error.value = ''
    state.value = 'closed'
  }

  async function cancel(id: string) {
    const result = await adapter.cancel(id)
    session.value = result
    return result
  }

  function fork(
    id: string,
    payload: { turn_id?: string; model?: string; message_id?: string } = {},
  ) {
    return adapter.fork(id, payload)
  }

  watch(
    () => stream.error.value,
    (cause) => {
      if (cause) error.value = formatError(cause)
    },
  )

  onScopeDispose(() => {
    generation++
    void adapter.close()
  })

  return {
    adapter,
    stream,
    messages: stream.messages,
    values: stream.values,
    events,
    session,
    state,
    error: errorMessage,
    cursor,
    select,
    submit,
    compact,
    resume,
    cancel,
    fork,
    clear,
  }
}
