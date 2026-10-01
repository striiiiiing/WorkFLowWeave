import { useQuery } from '@/shared/async/useQuery'
import { useSystemApi } from '../api/dependencies'
import type { SystemApi } from '../api/systemApi'
export function useSystemHealth(api: Pick<SystemApi, 'health'> = useSystemApi()) {
  return useQuery((signal) => api.health(signal))
}
