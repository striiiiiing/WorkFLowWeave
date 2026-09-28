import { effectScope, nextTick, ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  useRunDetail,
  useSession,
  SYNC_BUFFER_CAPACITY,
  createRunEventSource,
} from '@/modules/runs/public'
import { deferred, progress, runStream, session } from '../helpers/runHarness'

afterEach(() => vi.useRealTimers())

function setup(get = vi.fn().mockResolvedValue(session())) {
  const stream = runStream()
  const id = ref('one')
  const scope = effectScope()
  const query = scope.run(() => useSession(id, { get, subscribe: stream.subscribe }))!
  return { stream, get, id, scope, query }
}

describe('Workflow subscription synchronization', () => {
  it('queries only after ready, merges newer buffered items and never polls', async () => {
    vi.useFakeTimers()
    const snapshot = deferred<ReturnType<typeof session>>()
    const { stream, get, scope, query } = setup(vi.fn().mockReturnValue(snapshot.promise))
    expect(get).not.toHaveBeenCalled()
    stream.connections[0].handlers.ready()
    stream.connections[0].handlers.progress(
      progress({
        status: 'success',
        version: 3,
        result_ref: 'fast:epoch-one',
        label: null,
        availability: 'available',
      }),
    )
    snapshot.resolve(session())
    await flushPromises()
    expect(
      query.data.value?.progress.map((item) => [item.item_id, item.status, item.label]),
    ).toEqual([
      ['fast', 'success', '快速来源'],
      ['slow', 'pending', '慢速来源'],
    ])
    expect(query.data.value?.status).toBe('running')
    expect(query.data.value?.version).toBe(3)
    await vi.advanceTimersByTimeAsync(20_000)
    expect(get).toHaveBeenCalledTimes(1)
    scope.stop()
  })

  it('preserves results on disconnect and queries on the next ready to find a missed terminal event', async () => {
    const { stream, get, query, scope } = setup()
    const handlers = stream.connections[0].handlers
    handlers.ready()
    await flushPromises()
    handlers.progress(progress({ status: 'success', version: 3 }))
    handlers.disconnected('连接中断')
    expect(query.data.value?.progress[0].status).toBe('success')
    expect(query.data.value?.status).toBe('running')
    expect(query.connection.value).toBe('reconnecting')
    get.mockResolvedValue(
      session({
        version: 9,
        status: 'completed',
        stage: 'finish',
        finished_at: '2026-09-28T01:05:00Z',
        progress: [
          progress({ status: 'success', version: 3 }),
          progress({ item_id: 'slow', status: 'skipped' }),
        ],
      }),
    )
    handlers.ready()
    await flushPromises()
    expect(query.data.value?.status).toBe('completed')
    expect(query.data.value?.finished_at).toBe('2026-09-28T01:05:00Z')
    expect(query.connection.value).toBe('closed')
    expect(stream.connections[0].close).toHaveBeenCalledTimes(1)
    scope.stop()
  })

  it('confirms new epochs through queries and ignores late old epochs and stale query responses', async () => {
    const { stream, get, query, scope } = setup()
    const handlers = stream.connections[0].handlers
    handlers.ready()
    await flushPromises()
    const stale = deferred<ReturnType<typeof session>>()
    get.mockReturnValueOnce(stale.promise).mockResolvedValue(
      session({
        version: 11,
        execution_epoch: 'epoch-two',
        progress: [
          progress({ execution_epoch: 'epoch-two' }),
          progress({ item_id: 'slow', execution_epoch: 'epoch-two' }),
        ],
      }),
    )
    const refreshing = query.refresh()
    handlers.progress(
      progress({
        execution_epoch: 'epoch-two',
        event: 'lifecycle',
        stage: 'collect',
        status: 'running',
        item_id: null,
        version: 10,
      }),
    )
    handlers.progress(progress({ execution_epoch: 'epoch-two', status: 'success', version: 12 }))
    stale.resolve(session({ version: 2 }))
    await refreshing
    await flushPromises()
    expect(query.data.value?.execution_epoch).toBe('epoch-two')
    expect(query.data.value?.progress[0].status).toBe('success')
    handlers.progress(progress({ status: 'failed', version: 8 }))
    expect(query.data.value?.progress[0].status).toBe('success')
    expect(get).toHaveBeenCalledTimes(3)
    scope.stop()
  })

  it('reconciles terminal state without taking EOF as completion', async () => {
    const { stream, get, query, scope } = setup()
    const handlers = stream.connections[0].handlers
    handlers.ready()
    await flushPromises()
    const terminal = deferred<ReturnType<typeof session>>()
    get.mockReturnValueOnce(terminal.promise)
    handlers.progress(
      progress({
        event: 'lifecycle',
        stage: 'finish',
        status: 'completed',
        item_id: null,
        version: 10,
      }),
    )
    expect(query.connection.value).toBe('syncing')
    terminal.resolve(
      session({ version: 10, status: 'completed', stage: 'finish', finished_at: 'done' }),
    )
    await flushPromises()
    expect(query.connection.value).toBe('closed')
    expect(query.data.value?.finished_at).toBe('done')
    scope.stop()
  })

  it('aborts old queries and isolates callbacks after route switches and disposal', async () => {
    const first = deferred<ReturnType<typeof session>>()
    const { stream, get, id, query, scope } = setup(
      vi
        .fn()
        .mockReturnValueOnce(first.promise)
        .mockResolvedValue(session({ session_id: 'two' })),
    )
    const old = stream.connections[0]
    old.handlers.ready()
    id.value = 'two'
    await nextTick()
    expect(get.mock.calls[0][1].aborted).toBe(true)
    expect(old.close).toHaveBeenCalledTimes(1)
    stream.connections[1].handlers.ready()
    await flushPromises()
    first.resolve(session())
    old.handlers.progress(progress({ status: 'failed', version: 100 }))
    await flushPromises()
    expect(query.data.value?.session_id).toBe('two')
    scope.stop()
    stream.connections[1].handlers.progress(
      progress({ session_id: 'two', status: 'failed', version: 101 }),
    )
    await query.refresh()
    expect(query.data.value?.status).toBe('running')
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('explicitly stops an overflowing synchronization buffer and can resync', async () => {
    const slow = deferred<ReturnType<typeof session>>()
    const { stream, query, scope } = setup(vi.fn().mockReturnValue(slow.promise))
    const handlers = stream.connections[0].handlers
    handlers.ready()
    for (let i = 0; i <= SYNC_BUFFER_CAPACITY; i++)
      handlers.progress(progress({ item_id: `source-${i}`, version: i + 1 }))
    expect(query.connection.value).toBe('reconnecting')
    expect(query.connectionError.value).toContain('进度过多')
    expect(stream.connections[0].close).toHaveBeenCalledTimes(1)
    slow.resolve(session())
    await flushPromises()
    expect(query.data.value).toBeUndefined()
    await query.refresh()
    expect(stream.connections).toHaveLength(2)
    scope.stop()
  })

  it('shows an explicit unavailable subscription and never silently polls', async () => {
    vi.useFakeTimers()
    const get = vi.fn().mockResolvedValue(session())
    const stream = runStream()
    stream.subscribe.available = false
    const scope = effectScope()
    const query = scope.run(() => useSession(ref('one'), { get, subscribe: stream.subscribe }))!
    await flushPromises()
    expect(query.data.value?.session_id).toBe('one')
    expect(query.connection.value).toBe('reconnecting')
    expect(query.connectionError.value).toContain('不支持进度订阅')
    await vi.advanceTimersByTimeAsync(20_000)
    expect(get).toHaveBeenCalledTimes(1)
    expect(stream.subscribe).not.toHaveBeenCalled()
    scope.stop()
  })
})

it('reads only completed stage bodies at the relevant committed versions', async () => {
  const stream = runStream()
  const get = vi.fn().mockResolvedValue(session({ version: 2 }))
  const phase = vi.fn().mockResolvedValue({ availability: 'pending', content: null })
  const scope = effectScope()
  scope.run(() =>
    useRunDetail(ref('one'), {
      get,
      phase,
      subscribe: stream.subscribe,
      recovery: vi.fn().mockResolvedValue({ available: false, reason: null }),
      cancel: vi.fn().mockResolvedValue({ session_id: 'one', cancelled: true }),
    }),
  )
  const handlers = stream.connections[0].handlers
  handlers.ready()
  await flushPromises()
  expect(phase).toHaveBeenCalledTimes(5)

  handlers.progress(
    progress({ stage: 'analyze', item_id: 'analysis', status: 'success', version: 6 }),
  )
  await flushPromises()
  expect(phase).toHaveBeenCalledTimes(6)
  expect(phase).toHaveBeenLastCalledWith('one', 'collect', 6, expect.any(AbortSignal))

  handlers.progress(
    progress({
      stage: 'aggregate',
      event: 'aggregate',
      item_id: null,
      status: 'success',
      version: 8,
    }),
  )
  await flushPromises()
  expect(phase).toHaveBeenCalledTimes(9)
  expect(phase.mock.calls.slice(-3).map((call) => [call[1], call[2]])).toEqual([
    ['collect', 8],
    ['analyze', 8],
    ['aggregate', 8],
  ])

  get.mockResolvedValue(
    session({ version: 10, status: 'completed', stage: 'finish', finished_at: 'done' }),
  )
  handlers.progress(
    progress({
      event: 'lifecycle',
      stage: 'finish',
      status: 'completed',
      item_id: null,
      version: 10,
    }),
  )
  await flushPromises()
  expect(phase.mock.calls.slice(-5).map((call) => [call[1], call[2]])).toEqual([
    ['collect', 10],
    ['analyze', 10],
    ['aggregate', 10],
    ['notify', 10],
    ['finish', 10],
  ])
  scope.stop()
})

it('parses named SSE frames, rejects malformed payloads and releases its source', () => {
  const listeners = new Map<string, (event: MessageEvent) => void>()
  const source = {
    close: vi.fn(),
    onerror: null,
    addEventListener: vi.fn((name, listener) => listeners.set(name, listener)),
  }
  const factory = vi.fn().mockReturnValue(source)
  const handlers = { ready: vi.fn(), progress: vi.fn(), disconnected: vi.fn() }
  const close = createRunEventSource(factory)('run a', handlers)
  expect(factory).toHaveBeenCalledWith('/api/sessions/run%20a/events')
  listeners.get('ready')!(
    new MessageEvent('ready', { data: JSON.stringify({ session_id: 'run a' }) }),
  )
  listeners.get('progress')!(
    new MessageEvent('progress', {
      data: JSON.stringify(progress({ session_id: 'run a', status: 'success' })),
    }),
  )
  expect(handlers.ready).toHaveBeenCalledTimes(1)
  expect(handlers.progress).toHaveBeenCalledTimes(1)
  listeners.get('progress')!(new MessageEvent('progress', { data: '{bad' }))
  expect(handlers.disconnected).toHaveBeenCalledTimes(1)
  expect(source.close).toHaveBeenCalledTimes(1)
  close()
})
