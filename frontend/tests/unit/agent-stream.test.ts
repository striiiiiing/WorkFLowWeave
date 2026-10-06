import { effectScope, type EffectScope } from 'vue'
import { afterEach, expect, it, vi } from 'vitest'
import { useAgentSession } from '@/modules/agents/langchain/stream'
import type { AgentsApi } from '@/modules/agents/api/agentsApi'
import type { AgentEvent, AgentSession, TurnAccepted } from '@/modules/agents/model/types'

const session = (id = 's', status = 'completed'): AgentSession =>
  ({
    session_id: id,
    branch_id: 'main',
    model: null,
    workflow_session_id: null,
    created_at: '2026-10-06T00:00:00Z',
    updated_at: '2026-10-06T00:00:00Z',
    status,
    turn_id: 'previous-turn',
    context_budget: null,
    continuable: true,
    history_path: '',
    last_checkpoint_at: null,
  }) as AgentSession

const event = (id: number, type: string, data: Record<string, unknown>): AgentEvent => ({
  id,
  session_id: 's',
  turn_id: 'previous-turn',
  type,
  at: '2026-10-06T00:00:00Z',
  data,
})

class FakeEventSource {
  static instances: FakeEventSource[] = []
  onopen?: () => void
  onerror?: () => void
  onmessage?: (message: MessageEvent<string>) => void
  closed = false

  constructor(public readonly url: string) {
    FakeEventSource.instances.push(this)
    queueMicrotask(() => this.onopen?.())
  }

  close() {
    this.closed = true
  }

  emit(value: AgentEvent) {
    this.onmessage?.({ data: JSON.stringify(value) } as MessageEvent<string>)
  }
}

const scopes: EffectScope[] = []
afterEach(() => {
  scopes.splice(0).forEach((scope) => scope.stop())
  FakeEventSource.instances = []
  vi.unstubAllGlobals()
})

it('hydrates the SDK stream before opening SSE and submits messages through its adapter', async () => {
  vi.stubGlobal('EventSource', FakeEventSource)
  const accepted: TurnAccepted = {
    session_id: 's',
    turn_id: 'new-turn',
    deduplicated: false,
  }
  const api = {
    history: vi.fn(async () => []),
    get: vi.fn(async () => session()),
    send: vi.fn(async () => accepted),
    append: vi.fn(async () => accepted),
    cancel: vi.fn(async () => session()),
    compact: vi.fn(async () => accepted),
    fork: vi.fn(async () => session('forked')),
  } as unknown as AgentsApi
  const scope = effectScope()
  scopes.push(scope)
  const stream = scope.run(() => useAgentSession(api))!

  await stream.select('s')
  expect(stream.state.value).toBe('closed')
  expect(FakeEventSource.instances).toHaveLength(0)

  await expect(stream.submit('s', 'hello', 'request-1', false)).resolves.toEqual(accepted)
  expect(api.send).toHaveBeenCalledWith('s', 'request-1', 'hello')
})

it('projects replayed server events into the transcript and LangChain messages', async () => {
  vi.stubGlobal('EventSource', FakeEventSource)
  const api = {
    history: vi.fn(async () => []),
    get: vi.fn(async () => session('s', 'running')),
    send: vi.fn(async () => ({ session_id: 's', turn_id: 'new-turn', deduplicated: false })),
    append: vi.fn(async () => ({ session_id: 's', turn_id: 'new-turn', deduplicated: false })),
    cancel: vi.fn(async () => session()),
    compact: vi.fn(async () => ({ session_id: 's', turn_id: 'new-turn', deduplicated: false })),
    fork: vi.fn(async () => session('forked')),
  } as unknown as AgentsApi
  const scope = effectScope()
  scopes.push(scope)
  const stream = scope.run(() => useAgentSession(api))!
  await stream.select('s')
  await vi.waitFor(() => expect(stream.state.value).toBe('connected'))

  const incoming = event(1, 'message.user', { message_id: 'u1', text: 'replayed prompt' })
  await vi.waitFor(() => {
    for (const source of FakeEventSource.instances) if (!source.closed) source.emit(incoming)
    expect(stream.events.value).toContainEqual(incoming)
    expect(stream.messages.value.some((message) => message.content === 'replayed prompt')).toBe(
      true,
    )
  })
})
