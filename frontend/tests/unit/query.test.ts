/**
 * 查询组合函数单元测试：在 Vue effectScope 中控制异步请求、响应顺序和销毁，断言状态更新、错误及过期请求处理；用替身加载器隔离网络。
 */
import { effectScope, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { useQuery } from '@/shared/async/useQuery'
import { useSession } from '@/modules/runs/composables/useSession'
import { runsApi } from '@/app/services'
import type { SessionRecord } from '@/modules/runs/public'
import { session } from '../helpers/runHarness'

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
    const pending = deferred<string>()
    const fetcher = vi.fn().mockReturnValue(pending.promise)
    const scope = effectScope()
    const query = scope.run(() => useQuery(fetcher))!
    scope.stop()
    expect(fetcher.mock.calls[0][0].aborted).toBe(true)
    pending.resolve('late result')
    await flushPromises()
    expect(query.data.value).toBeUndefined()
    expect(query.readAt.value).toBeUndefined()
    expect(query.pending.value).toBe(false)
    await query.refresh()
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
  it('records read time only for the accepted response and keeps stale data on same identity failure', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce('initial')
      .mockRejectedValue(new Error('refresh failed'))
    const key = ref('same')
    const scope = effectScope()
    const query = scope.run(() => useQuery(fetcher, [key]))!
    await flushPromises()
    expect(query.data.value).toBe('initial')
    expect(query.readAt.value).toEqual(expect.any(Number))
    const firstRead = query.readAt.value
    await query.refresh()
    expect(query.data.value).toBe('initial')
    expect(query.readAt.value).toBe(firstRead)
    expect(query.error.value).toBe('refresh failed')
    key.value = 'changed'
    await nextTick()
    expect(query.data.value).toBeUndefined()
    expect(query.readAt.value).toBeUndefined()
    scope.stop()
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
describe('session snapshots without subscriptions', () => {
  it('reads one snapshot and requires explicit synchronization', async () => {
    vi.useFakeTimers()
    const initial = deferred<SessionRecord>()
    const get = vi
      .spyOn(runsApi, 'get')
      .mockReturnValueOnce(initial.promise)
      .mockResolvedValue(session({ session_id: 'run_1', status: 'interrupted' }))
    const scope = effectScope()
    const query = scope.run(() => useSession(ref('run_1'), { get }))!
    await vi.advanceTimersByTimeAsync(20_000)
    expect(get).toHaveBeenCalledTimes(1)
    initial.resolve(session({ session_id: 'run_1' }))
    await flushPromises()
    expect(query.connectionError.value).toContain('不支持进度订阅')
    await vi.advanceTimersByTimeAsync(20_000)
    expect(get).toHaveBeenCalledTimes(1)
    await query.refresh()
    expect(get).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(20_000)
    expect(get).toHaveBeenCalledTimes(2)
    scope.stop()
  })
  it('surfaces read failures and allows an explicit retry', async () => {
    vi.useFakeTimers()
    vi.spyOn(runsApi, 'get')
      .mockRejectedValueOnce(new Error('network unavailable'))
      .mockResolvedValue(session({ session_id: 'run_1', status: 'completed' }))
    const scope = effectScope()
    const query = scope.run(() => useSession(ref('run_1'), { get: runsApi.get }))!
    await flushPromises()
    expect(query.error.value).toBe('network unavailable')
    await query.refresh()
    expect(query.error.value).toBe('')
    expect(query.data.value?.status).toBe('completed')
    scope.stop()
  })
})
