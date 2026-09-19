import { request, segment } from './client'
import type { PhaseContent, SessionRecord, WorkflowStage } from '@/types'

export interface SessionQuery {
  workflow_id?: string
  limit?: number
  offset?: number
  after?: string
  before?: string
}
export const runsApi = {
  list(query: SessionQuery = {}, signal?: AbortSignal) {
    const params = new URLSearchParams()
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== '') params.set(key, String(value))
    })
    return request<SessionRecord[]>(`/sessions?${params}`, { signal })
  },
  get: (id: string, signal?: AbortSignal) =>
    request<SessionRecord>(`/sessions/${segment(id)}`, { signal }),
  phase: (id: string, stage: WorkflowStage, version: number, signal?: AbortSignal) =>
    request<PhaseContent>(`/sessions/${segment(id)}/phases/${stage}?version=${version}`, {
      signal,
    }),
  trigger: (id: string) =>
    request<{ session_id: string }>(`/workflows/${segment(id)}/run`, { method: 'POST' }),
  recover: (id: string) =>
    request<{ session_id: string }>(`/sessions/${segment(id)}/recover`, { method: 'POST' }),
  cancel: (id: string) =>
    request<{ session_id: string; cancelled: boolean }>(`/sessions/${segment(id)}/cancel`, {
      method: 'POST',
    }),
}
