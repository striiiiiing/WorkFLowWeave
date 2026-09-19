import { onScopeDispose, watch, type Ref } from 'vue'
import { runsApi } from '@/api/runs'
import { sessionStates } from '@/domain/session'
import { useQuery } from './useQuery'

export const POLL_INTERVAL_MS = 2000
export function useSession(id: Ref<string>) {
  const query = useQuery((signal) => runsApi.get(id.value, signal), [id])
  let timer: ReturnType<typeof setTimeout> | undefined
  // Schedule after completion so slow requests cannot overlap polling ticks.
  watch([query.pending, query.data, query.error], () => {
    clearTimeout(timer)
    if (
      !query.pending.value &&
      !query.error.value &&
      query.data.value &&
      sessionStates[query.data.value.status].active
    ) {
      timer = setTimeout(() => {
        void query.refresh()
      }, POLL_INTERVAL_MS)
    }
  })
  onScopeDispose(() => clearTimeout(timer))
  return query
}
