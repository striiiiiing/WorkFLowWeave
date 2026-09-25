import { ApiError } from '@/shared/api/errors'
import { useAsyncTask, type AsyncTaskResult } from '@/shared/async/useAsyncTask'
import { useRunsApi } from '../api/dependencies'
import type { RunsApi } from '../api/runsApi'

export type RunActionResult<T> =
  | { status: 'success'; value: T }
  | { status: 'failure' | 'unknown'; error: unknown; message: string }
  | { status: 'busy' }

class CancellationDeclinedError extends Error {
  constructor() {
    super('后端未接受取消请求，请刷新运行状态')
    this.name = 'CancellationDeclinedError'
  }
}

function classify<T>(result: AsyncTaskResult<T>): RunActionResult<T> {
  if (result.status !== 'error') return result
  // Only an explicit client/business rejection proves the write was declined.
  const rejected =
    result.error instanceof CancellationDeclinedError ||
    (result.error instanceof ApiError && result.error.status >= 400 && result.error.status < 500)
  return { ...result, status: rejected ? 'failure' : 'unknown' }
}

export function useCancelAction(api: Pick<RunsApi, 'cancel'> = useRunsApi()) {
  const task = useAsyncTask()
  return {
    pending: task.pending,
    error: task.error,
    async cancel(sessionId: string) {
      return classify(
        await task.run(async () => {
          const result = await api.cancel(sessionId)
          if (result.cancelled === false) throw new CancellationDeclinedError()
          if (result.cancelled !== true)
            throw new Error('取消响应缺少有效的 cancelled 字段，结果未知')
          return result
        }),
      )
    },
  }
}
/** Trigger and cancel have separate pending states so cancellation remains available. */
export function useRunActions(api: Pick<RunsApi, 'trigger' | 'cancel'> = useRunsApi()) {
  const triggering = useAsyncTask()
  const cancelling = useCancelAction(api)
  return {
    triggering: triggering.pending,
    cancelling: cancelling.pending,
    triggerError: triggering.error,
    cancelError: cancelling.error,
    async trigger(workflowId: string, signal?: AbortSignal) {
      return classify(await triggering.run(() => api.trigger(workflowId, signal)))
    },
    cancel: cancelling.cancel,
  }
}

export function useRecoveryAction(api: Pick<RunsApi, 'recover'> = useRunsApi()) {
  const task = useAsyncTask()
  return {
    pending: task.pending,
    error: task.error,
    async recover(id: string) {
      return classify(await task.run(() => api.recover(id)))
    },
  }
}
