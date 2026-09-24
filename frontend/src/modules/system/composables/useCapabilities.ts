import { useQuery } from '@/shared/async/useQuery'
import { useSystemApi } from '../api/dependencies'
import type { SystemApi } from '../api/systemApi'

/** One capability query per page scope; callers pass the injected module API in tests. */
export function useCapabilities(api: Pick<SystemApi, 'plugins'> = useSystemApi()) {
  return useQuery((signal) => api.plugins(signal))
}
