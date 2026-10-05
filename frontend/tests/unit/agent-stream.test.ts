import { effectScope, type EffectScope } from 'vue'
import { afterEach, expect, it, vi } from 'vitest'
import { services } from '@/app/services'
import { useAgentSession, type AgentEvent, type AgentSession } from '@/modules/agents/public'
import { createAgentEventSource } from '@/modules/agents/api/agentEventSource'
import { mergeAgentEvents } from '@/modules/agents/model/events'
const { agentsApi } = services
class FakeEventSource {
  static instances: FakeEventSource[] = []
  onopen?: () => void
  onerror?: () => void
  onmessage?: (message: { data: string }) => void
  closed = false
  constructor(public url: string) {
    FakeEventSource.instances.push(this)
  }
  close() {
    this.closed = true
  }
  emit(event: AgentEvent) {
    this.onmessage?.({ data: JSON.stringify(event) })
  }
}
const event = (id: number, type = 'message.delta', session = 's', turn = 't'): AgentEvent => ({
  id,
  session_id: session,
  turn_id: turn,
  type,
  at: '2026-09-23',
  data: type === 'message.user' ? { text: 'hello' } : { content: 'chunk' },
})
const scopes: EffectScope[] = []
function setup() {
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.spyOn(agentsApi, 'history').mockResolvedValue([])
  vi.spyOn(agentsApi, 'get').mockResolvedValue({
    session_id: 's',
    status: 'running',
    turn_id: 't',
  } as AgentSession)
  const callback = vi.fn()
  const scope = effectScope()
  scopes.push(scope)
  return {
    stream: scope.run(() => useAgentSession(agentsApi, createAgentEventSource(), callback))!,
    callback,
  }
}
afterEach(() => {
  scopes.splice(0).forEach((scope) => scope.stop())
  FakeEventSource.instances = []
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
it('reconnects repeatedly from the durable cursor, deduplicates and closes at the terminal', async () => {
  vi.useFakeTimers()
  const { stream, callback } = setup()
  await stream.select('s')
  const first = FakeEventSource.instances[0]
  expect(first.url).toContain('/api/channels/web/sessions/s/events')
  first.emit(event(1))
  first.onerror?.()
  expect(stream.state.value).toBe('reconnecting')
  await vi.advanceTimersByTimeAsync(500)
  const second = FakeEventSource.instances[1]
  expect(second.url).toContain('after=1')
  second.emit(event(1))
  second.emit(event(2))
  second.onerror?.()
  await vi.advanceTimersByTimeAsync(1000)
  const third = FakeEventSource.instances[2]
  expect(third.url).toContain('after=2')
  first.onerror?.() // A stale source cannot close its replacement.
  expect(third.closed).toBe(false)
  third.emit(event(3, 'turn.completed'))
  await vi.advanceTimersByTimeAsync(10000)
  expect(FakeEventSource.instances).toHaveLength(3)
  expect(callback).toHaveBeenCalledTimes(3)
  expect(stream.events.value.map((item) => item.id)).toEqual([1, 2, 3])
  expect(stream.state.value).toBe('closed')
})
it('retains inherited IDs, restores completed history without reconnecting, and resumes the next turn', async () => {
  const { stream, callback } = setup()
  vi.mocked(agentsApi.history).mockResolvedValue([
    event(1, 'message.user', 'parent'),
    event(1, 'turn.completed'),
  ])
  vi.mocked(agentsApi.get).mockResolvedValue({
    session_id: 's',
    status: 'completed',
    turn_id: 't',
  } as AgentSession)
  await stream.select('s')
  expect(FakeEventSource.instances).toHaveLength(0)
  expect(stream.events.value).toHaveLength(2)
  stream.resume('next')
  const connection = FakeEventSource.instances[0]
  expect(connection.url).toContain('after=1')
  connection.emit(event(2, 'turn.completed', 's', 't'))
  expect(connection.closed).toBe(false)
  expect(callback).not.toHaveBeenCalled()
  connection.emit(event(3, 'turn.started', 's', 'next'))
  connection.emit(event(4, 'turn.completed', 's', 'next'))
  expect(connection.closed).toBe(true)
  expect(callback).toHaveBeenCalledTimes(2)
})
it('ignores stale history and source callbacks after selecting another branch', async () => {
  const { stream } = setup()
  let finish!: (value: AgentEvent[]) => void
  vi.mocked(agentsApi.history).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve
      }),
  )
  const first = stream.select('parent')
  await stream.select('s')
  finish([event(99, 'message.user', 'parent')])
  await first
  expect(stream.events.value).toEqual([])
  const source = FakeEventSource.instances[0]
  stream.clear()
  source.emit(event(1))
  expect(stream.events.value).toEqual([])
  expect(source.closed).toBe(true)
})
it('surfaces malformed SSE instead of pretending the response completed', async () => {
  const { stream } = setup()
  await stream.select('s')
  FakeEventSource.instances[0].onmessage?.({ data: 'not json' })
  expect(stream.error.value).toBeTruthy()
  expect(stream.state.value).toBe('closed')
  expect(stream.events.value).toEqual([])
})
it('deduplicates within each session while preserving parent and child history order', () => {
  const parent = event(1, 'message.user', 'parent')
  const child = event(1, 'message.user', 'child')
  expect(mergeAgentEvents([parent], [parent, child, child])).toEqual([parent, child])
})
