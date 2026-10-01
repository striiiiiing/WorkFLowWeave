import { ref } from 'vue'
import { useErrorFormatter } from './errorFormatter'

/** UI action boundary: failures stay visible until the next attempt. */
export type AsyncTaskResult<T> =
  | { status: 'success'; value: T }
  | { status: 'error'; error: unknown; message: string }
  | { status: 'busy' }

export function isTaskSuccess<T>(
  result: AsyncTaskResult<T>,
): result is { status: 'success'; value: T } {
  return result.status === 'success'
}

export function useAsyncTask() {
  const errorMessage = useErrorFormatter()
  const pending = ref(false)
  const error = ref('')
  async function run<T>(action: () => Promise<T>): Promise<AsyncTaskResult<T>> {
    if (pending.value) return { status: 'busy' }
    pending.value = true
    error.value = ''
    try {
      return { status: 'success', value: await action() }
    } catch (cause) {
      const message = errorMessage(cause)
      error.value = message
      return { status: 'error', error: cause, message }
    } finally {
      pending.value = false
    }
  }
  return { pending, error, run }
}
