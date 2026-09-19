import { effectScope, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { useQuery } from '@/composables/useQuery'
import { useSession, POLL_INTERVAL_MS } from '@/composables/useSession'
import { runsApi } from '@/api/runs'
import type { SessionRecord } from '@/types'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}
afterEach(() => vi.useRealTimers())
describe('request ownership', () => {
  it('discards an older response even if transport ignores cancellation', async () => {
    const first = deferred<string>()
    const second = deferred<string>()
    const fetcher = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const key = ref('first')
    const scope = effectScope()
    const query = scope.run(() => useQuery(fetcher, [key]))!
    key.value = 'second'
    await nextTick()
    second.resolve('new result')
    await flushPromises()
    first.resolve('stale result')
    await flushPromises()
    expect(query.data.value).toBe('new result')
    expect(fetcher.mock.calls[0][0].aborted).toBe(true)
    scope.stop()
  })
  it('aborts a request and prevents delayed refresh after disposal', async () => {
    let signal!: AbortSignal
    const scope = effectScope()
    scope.run(() =>
      useQuery((current) => {
        signal = current
        return new Promise(() => {})
      }),
    )
    scope.stop()
    expect(signal.aborted).toBe(true)
  })
})
it('does not start new reads after its scope is disposed', async () => {
  const fetcher = vi.fn().mockResolvedValue('value')
  const scope = effectScope()
  const query = scope.run(() => useQuery(fetcher))!
  scope.stop()
  await query.refresh()
  expect(fetcher).toHaveBeenCalledTimes(1)
})
describe('session polling', () => {
  it('does not overlap slow requests and stops on interrupted status', async () => {
    vi.useFakeTimers()
    const initial = deferred<SessionRecord>()
    const get = vi
      .spyOn(runsApi, 'get')
      .mockReturnValueOnce(initial.promise)
      .mockResolvedValue({ status: 'interrupted' } as SessionRecord)
    const scope = effectScope()
    scope.run(() => useSession(ref('run_1')))
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 4)
    expect(get).toHaveBeenCalledTimes(1)
    initial.resolve({ status: 'running' } as SessionRecord)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(get).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3)
    expect(get).toHaveBeenCalledTimes(2)
    scope.stop()
  })
  it('surfaces polling failures and allows an explicit retry', async () => {
    vi.useFakeTimers()
    vi.spyOn(runsApi, 'get')
      .mockRejectedValueOnce(new Error('network unavailable'))
      .mockResolvedValue({ status: 'completed' } as SessionRecord)
    const scope = effectScope()
    const query = scope.run(() => useSession(ref('run_1')))!
    await flushPromises()
    expect(query.error.value).toBe('network unavailable')
    await query.refresh()
    expect(query.error.value).toBe('')
    expect(query.data.value?.status).toBe('completed')
    scope.stop()
  })
})
