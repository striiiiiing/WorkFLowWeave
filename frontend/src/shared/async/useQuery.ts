import { onScopeDispose, shallowRef, ref, watch, type WatchSource } from 'vue'
import { useErrorFormatter } from './errorFormatter'

/** Only the latest request owns the view; leaving the scope aborts its work. */
export function useQuery<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  sources: WatchSource[] = [],
) {
  const data = shallowRef<T>()
  const errorMessage = useErrorFormatter()
  const pending = ref(false)
  const error = ref('')
  let controller: AbortController | undefined
  let disposed = false
  async function refresh() {
    if (disposed) return
    controller?.abort()
    const current = new AbortController()
    controller = current
    pending.value = true
    error.value = ''
    try {
      const result = await fetcher(current.signal)
      if (!current.signal.aborted) data.value = result
    } catch (cause) {
      if (!current.signal.aborted) error.value = errorMessage(cause)
    } finally {
      if (!current.signal.aborted) pending.value = false
    }
  }
  watch(
    sources,
    () => {
      data.value = undefined
      void refresh()
    },
    { immediate: true },
  )
  onScopeDispose(() => {
    disposed = true
    controller?.abort()
  })
  return { data, pending, error, refresh }
}
