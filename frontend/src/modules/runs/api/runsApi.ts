import { segment, type HttpClient } from '@/shared/api'
import type {
  PhaseContent,
  RecoveryAvailability,
  SessionRecord,
  WorkflowStage,
} from '../model/types'
export interface SessionQuery {
  workflow_id?: string
  workflow_name?: string
  session_id?: string
  status?: SessionRecord['status']
  limit?: number
  offset?: number
  after?: string
  before?: string
}
export function createRunsApi(http: HttpClient) {
  return {
    list: (query: SessionQuery = {}, signal?: AbortSignal) =>
      http.request<SessionRecord[]>({
        url: '/sessions',
        params: Object.fromEntries(
          Object.entries(query).filter(([, value]) => value !== undefined && value !== ''),
        ),
        signal,
      }),
    get: (id: string, signal?: AbortSignal) =>
      http.request<SessionRecord>({ url: `/sessions/${segment(id)}`, signal }),
    phase: (id: string, stage: WorkflowStage, version: number, signal?: AbortSignal) =>
      http.request<PhaseContent>({
        url: `/sessions/${segment(id)}/phases/${stage}`,
        params: { version },
        signal,
      }),
    trigger: (id: string, signal?: AbortSignal) =>
      http.request<{ session_id: string }>({
        url: `/workflows/${segment(id)}/run`,
        method: 'POST',
        signal,
      }),
    recover: (id: string) =>
      http.request<{ session_id: string }>({
        url: `/sessions/${segment(id)}/recover`,
        method: 'POST',
      }),
    recovery: (id: string, signal?: AbortSignal) =>
      http.request<RecoveryAvailability>({ url: `/sessions/${segment(id)}/recovery`, signal }),
    cancel: (id: string) =>
      http.request<{ session_id: string; cancelled: boolean }>({
        url: `/sessions/${segment(id)}/cancel`,
        method: 'POST',
      }),
  }
}
export type RunsApi = ReturnType<typeof createRunsApi>
