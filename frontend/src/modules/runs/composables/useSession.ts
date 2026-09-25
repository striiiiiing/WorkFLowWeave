import { onScopeDispose, watch, type Ref } from 'vue'
import { useRunsApi } from '../api/dependencies'
import type { RunsApi } from '../api/runsApi'
import { sessionStates } from '../model/session'
import { useQuery } from '@/shared/async/useQuery'

export const POLL_INTERVAL_MS = 2000
export function useSession(id: Ref<string>, api: Pick<RunsApi, 'get'> = useRunsApi()) {
  const query = useQuery((signal) => api.get(id.value, signal), [id])
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
