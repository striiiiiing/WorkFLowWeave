import { useQuery } from '@/shared/async/useQuery'
import { useWorkflowsApi } from '../api/dependencies'
import type { WorkflowsApi } from '../api/workflowsApi'

export function useWorkflowList(api: Pick<WorkflowsApi, 'list'> = useWorkflowsApi()) {
  return useQuery((signal) => api.list(signal))
}
