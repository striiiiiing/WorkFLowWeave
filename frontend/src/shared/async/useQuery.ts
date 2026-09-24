import { onScopeDispose, shallowReadonly, shallowRef, ref, watch, type WatchSource } from 'vue'
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
  const readAt = ref<number>()
  let controller: AbortController | undefined
  let disposed = false
  let generation = 0

  async function load(clear: boolean) {
    if (disposed) return
    controller?.abort()
    const current = new AbortController()
    const requestGeneration = ++generation
    controller = current
    if (clear) {
      data.value = undefined
      readAt.value = undefined
    }
    pending.value = true
    error.value = ''
    try {
      const result = await fetcher(current.signal)
      if (!current.signal.aborted && requestGeneration === generation) {
        data.value = result
        readAt.value = Date.now()
      }
    } catch (cause) {
      if (!current.signal.aborted && requestGeneration === generation)
        error.value = errorMessage(cause)
    } finally {
      if (requestGeneration === generation) pending.value = false
    }
  }

  async function refresh() {
    await load(false)
  }
  watch(
    sources,
    () => {
      void load(true)
    },
    { immediate: true },
  )
  onScopeDispose(() => {
    disposed = true
    generation++
    controller?.abort()
    pending.value = false
  })
  return {
    data: shallowReadonly(data),
    pending: shallowReadonly(pending),
    error: shallowReadonly(error),
    readAt: shallowReadonly(readAt),
    refresh,
  }
}
