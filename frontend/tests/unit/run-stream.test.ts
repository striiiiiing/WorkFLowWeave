import { effectScope, nextTick, ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createRunEventSource, useRunDetail, useSession } from '@/modules/runs/public'
import { deferred, progress, runStream, session } from '../helpers/runHarness'

afterEach(() => vi.useRealTimers())

function setup(get = vi.fn().mockResolvedValue(session())) {
  const stream = runStream()
  const id = ref('one')
  const scope = effectScope()
  const query = scope.run(() => useSession(id, { get, subscribe: stream.subscribe }))!
  return { stream, get, id, scope, query }
}

describe('Workflow snapshot subscription', () => {
  it('accepts whole snapshots, ignores stale versions and never polls', async () => {
    vi.useFakeTimers()
    const { stream, get, scope, query } = setup()
    const first = stream.connections[0].handlers
    expect(get).not.toHaveBeenCalled()
    first.snapshot(session({ version: 3, progress: [progress({ status: 'success', version: 3 })] }))
    expect(query.data.value?.progress).toHaveLength(1)
    first.snapshot(session({ version: 2 }))
    expect(query.data.value?.version).toBe(3)
    expect(query.data.value?.progress).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(20_000)
    expect(get).not.toHaveBeenCalled()
    scope.stop()
  })

  it('preserves the last view across disconnect and switches epoch from a higher version', () => {
    const { stream, query, scope } = setup()
    const handlers = stream.connections[0].handlers
    handlers.snapshot(session({ version: 3 }))
    handlers.state('reconnecting')
    expect(query.data.value?.version).toBe(3)
    expect(query.connection.value).toBe('reconnecting')
    handlers.snapshot(session({ version: 4, execution_epoch: 'epoch-two', progress: [] }))
    expect(query.data.value?.execution_epoch).toBe('epoch-two')
    expect(query.data.value?.progress).toEqual([])
    expect(query.connection.value).toBe('connected')
    scope.stop()
  })

  it('closes on a terminal snapshot without interpreting disconnect as completion', () => {
    const { stream, query, scope } = setup()
    const handlers = stream.connections[0].handlers
    handlers.state('reconnecting')
    expect(query.data.value).toBeUndefined()
    handlers.snapshot(session({ version: 9, status: 'completed', stage: 'finish' }))
    expect(query.connection.value).toBe('closed')
    expect(stream.connections[0].close).toHaveBeenCalledTimes(1)
    scope.stop()
  })

  it('isolates stale callbacks and GET responses after route changes and disposal', async () => {
    const first = deferred<ReturnType<typeof session>>()
    const { stream, get, id, query, scope } = setup(
      vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue(session({ session_id: 'two' })),
    )
    const old = stream.connections[0]
    const refreshing = query.refresh()
    id.value = 'two'
    await nextTick()
    expect(get.mock.calls[0][1].aborted).toBe(true)
    expect(old.close).toHaveBeenCalled()
    stream.connections[2].handlers.snapshot(session({ session_id: 'two' }))
    first.resolve(session({ version: 100 }))
    await refreshing
    old.handlers.snapshot(session({ version: 101 }))
    expect(query.data.value?.session_id).toBe('two')
    scope.stop()
    stream.connections[2].handlers.snapshot(session({ session_id: 'two', version: 5 }))
    expect(query.data.value?.version).toBe(1)
  })

  it('uses GET only for an explicit refresh and rejects stale reads', async () => {
    const old = deferred<ReturnType<typeof session>>()
    const { stream, get, query, scope } = setup(vi.fn().mockReturnValue(old.promise))
    const refreshing = query.refresh()
    stream.connections[1].handlers.snapshot(session({ version: 7 }))
    old.resolve(session({ version: 2 }))
    await refreshing
    expect(query.data.value?.version).toBe(7)
    expect(get).toHaveBeenCalledTimes(1)
    scope.stop()
  })

  it('reads once when EventSource is unavailable', async () => {
    const get = vi.fn().mockResolvedValue(session())
    const stream = runStream()
    stream.subscribe.available = false
    const scope = effectScope()
    const query = scope.run(() => useSession(ref('one'), { get, subscribe: stream.subscribe }))!
    await flushPromises()
    expect(query.data.value?.session_id).toBe('one')
    expect(query.connection.value).toBe('reconnecting')
    expect(stream.subscribe).not.toHaveBeenCalled()
    scope.stop()
  })
})

it('reads only available artifact content versions', async () => {
  const stream = runStream()
  const phase = vi.fn().mockResolvedValue({ availability: 'available', content: {} })
  const scope = effectScope()
  scope.run(() => useRunDetail(ref('one'), {
    get: vi.fn().mockResolvedValue(session()),
    phase,
    subscribe: stream.subscribe,
    recovery: vi.fn().mockResolvedValue({ available: false, reason: null }),
    cancel: vi.fn().mockResolvedValue({ session_id: 'one', cancelled: true }),
  }))
  const handlers = stream.connections[0].handlers
  handlers.snapshot(session({ version: 2 }))
  await flushPromises()
  expect(phase).not.toHaveBeenCalled()
  handlers.snapshot(session({ version: 3, artifacts: [
    { stage: 'collect', availability: 'available', content_version: 2, size_bytes: null, error: null },
    { stage: 'analyze', availability: 'pending', content_version: null, size_bytes: null, error: null },
  ] }))
  await flushPromises()
  expect(phase).toHaveBeenCalledOnce()
  expect(phase).toHaveBeenCalledWith('one', 'collect', 2, expect.any(AbortSignal))
  handlers.snapshot(session({ version: 4, artifacts: [
    { stage: 'collect', availability: 'available', content_version: 2, size_bytes: null, error: null },
    { stage: 'aggregate', availability: 'available', content_version: 4, size_bytes: null, error: null },
  ] }))
  await flushPromises()
  expect(phase).toHaveBeenCalledTimes(2)
  expect(phase).toHaveBeenLastCalledWith('one', 'aggregate', 4, expect.any(AbortSignal))
  scope.stop()
})

it('parses named snapshot frames, retries with one owner and rejects malformed payloads', async () => {
  vi.useFakeTimers()
  const sources: { listeners: Map<string, (event: MessageEvent<string>) => void>; close: ReturnType<typeof vi.fn>; onopen?: () => void; onerror?: () => void }[] = []
  const factory = vi.fn(() => {
    const source = { listeners: new Map(), close: vi.fn(), onopen: undefined as (() => void) | undefined,
      onerror: undefined as (() => void) | undefined,
      addEventListener(name: string, listener: (event: MessageEvent<string>) => void) { this.listeners.set(name, listener) } }
    sources.push(source)
    return source
  })
  const handlers = { snapshot: vi.fn(), state: vi.fn(), error: vi.fn() }
  const close = createRunEventSource(factory)('run a', handlers)
  expect(factory).toHaveBeenCalledWith('/api/sessions/run%20a/events')
  sources[0].listeners.get('snapshot')!(new MessageEvent('snapshot', { data: JSON.stringify(session({ session_id: 'run a' })) }))
  expect(handlers.snapshot).toHaveBeenCalledOnce()
  sources[0].onerror?.()
  expect(sources[0].close).toHaveBeenCalledOnce()
  await vi.advanceTimersByTimeAsync(500)
  sources[0].listeners.get('snapshot')!(new MessageEvent('snapshot', { data: '{bad' }))
  expect(handlers.error).not.toHaveBeenCalled()
  sources[1].listeners.get('snapshot')!(new MessageEvent('snapshot', { data: '{bad' }))
  expect(handlers.error).toHaveBeenCalledOnce()
  expect(sources[1].close).toHaveBeenCalledOnce()
  close()
})
