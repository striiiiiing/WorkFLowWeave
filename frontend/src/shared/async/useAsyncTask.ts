import { ref } from 'vue'
import { useErrorFormatter } from './errorFormatter'

/** UI action boundary: failures stay visible until the next attempt. */
export function useAsyncTask() {
  const errorMessage = useErrorFormatter()
  const pending = ref(false)
  const error = ref('')
  async function run<T>(action: () => Promise<T>): Promise<T | undefined> {
    if (pending.value) return
    pending.value = true
    error.value = ''
    try {
      return await action()
    } catch (cause) {
      error.value = errorMessage(cause)
    } finally {
      pending.value = false
    }
  }
  return { pending, error, run }
}
