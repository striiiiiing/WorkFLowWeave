import { effectScope } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useRunActions, type RunsApi } from '@/modules/runs/public'
import { ApiError, NetworkError, RequestCancelledError } from '@/shared/api'

function setup() {
  const api = {
    trigger: vi.fn<RunsApi['trigger']>().mockResolvedValue({ session_id: 'run' }),
    cancel: vi.fn<RunsApi['cancel']>().mockResolvedValue({ session_id: 'run', cancelled: true }),
  }
  const scope = effectScope()
  const actions = scope.run(() => useRunActions(api))!
  return { api, actions, scope }
}

describe('runs actions', () => {
  it('returns accepted writes and forwards workflow identity and cancellation signal', async () => {
    const { api, actions, scope } = setup()
    const signal = new AbortController().signal
    expect(await actions.trigger('workflow', signal)).toEqual({
      status: 'success',
      value: { session_id: 'run' },
    })
    expect(api.trigger).toHaveBeenCalledWith('workflow', signal)
    expect(await actions.cancel('run')).toEqual({
      status: 'success',
      value: { session_id: 'run', cancelled: true },
    })
    scope.stop()
  })

  it('reports declined cancellation as failure with a visible error', async () => {
    const { api, actions, scope } = setup()
    api.cancel.mockResolvedValue({ session_id: 'run', cancelled: false })
    expect(await actions.cancel('run')).toMatchObject({ status: 'failure' })
    expect(actions.cancelError.value).toContain('未接受取消请求')
    scope.stop()
  })

  it.each([
    [new ApiError(409, { code: 'conflict', message: 'declined', details: {} }), 'failure'],
    [new ApiError(503, { code: 'unavailable', message: 'unavailable', details: {} }), 'unknown'],
    [new NetworkError('/run', new Error('offline')), 'unknown'],
    [new RequestCancelledError('/run', new Error('abort')), 'unknown'],
  ] as const)('classifies %s without retrying the write', async (error, status) => {
    const { api, actions, scope } = setup()
    api.trigger.mockRejectedValue(error)
    expect(await actions.trigger('workflow')).toMatchObject({ status, error })
    expect(api.trigger).toHaveBeenCalledTimes(1)
    expect(actions.triggerError.value).not.toBe('')
    scope.stop()
  })

  it('rejects duplicate triggers while keeping cancellation independent', async () => {
    const { api, actions, scope } = setup()
    let resolve!: (value: { session_id: string }) => void
    api.trigger.mockReturnValue(
      new Promise((done) => {
        resolve = done
      }),
    )
    const first = actions.trigger('workflow')
    expect(actions.triggering.value).toBe(true)
    expect(await actions.trigger('workflow')).toEqual({ status: 'busy' })
    expect((await actions.cancel('run')).status).toBe('success')
    expect(api.trigger).toHaveBeenCalledTimes(1)
    resolve({ session_id: 'run' })
    await first
    expect(actions.triggering.value).toBe(false)
    scope.stop()
  })
})
