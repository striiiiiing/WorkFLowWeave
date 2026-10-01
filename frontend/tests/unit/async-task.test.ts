import { effectScope } from 'vue'
import { describe, expect, it } from 'vitest'
import { isTaskSuccess, useAsyncTask } from '@/shared/async/useAsyncTask'

describe('useAsyncTask result contract', () => {
  it('distinguishes void success, failure and busy rejection', async () => {
    const scope = effectScope()
    const task = scope.run(() => useAsyncTask())!
    const first = task.run(async () => undefined)
    const busy = await task.run(async () => 'ignored')
    expect(busy).toEqual({ status: 'busy' })
    expect(await first).toEqual({ status: 'success', value: undefined })
    const failure = await task.run(async () => {
      throw new Error('failed')
    })
    expect(failure.status).toBe('error')
    if (failure.status === 'error') expect(failure.message).toBe('failed')
    expect(isTaskSuccess(failure)).toBe(false)
    scope.stop()
  })
})
