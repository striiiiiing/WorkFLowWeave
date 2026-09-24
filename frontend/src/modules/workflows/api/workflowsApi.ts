import { segment, type HttpClient } from '@/shared/api'
import type { WorkflowDefinition } from '../model/types'
export function createWorkflowsApi(http: HttpClient) {
  return {
    list: (signal?: AbortSignal) =>
      http.request<WorkflowDefinition[]>({ url: '/workflows', signal }),
    get: (id: string, signal?: AbortSignal) =>
      http.request<WorkflowDefinition>({ url: `/workflows/${segment(id)}`, signal }),
    create: (data: WorkflowDefinition) =>
      http.request<WorkflowDefinition>({ url: '/workflows', method: 'POST', data }),
    replace: (id: string, data: WorkflowDefinition) =>
      http.request<WorkflowDefinition>({ url: `/workflows/${segment(id)}`, method: 'PUT', data }),
    delete: (id: string) =>
      http.request<void>({ url: `/workflows/${segment(id)}`, method: 'DELETE' }),
  }
}
export type WorkflowsApi = ReturnType<typeof createWorkflowsApi>
