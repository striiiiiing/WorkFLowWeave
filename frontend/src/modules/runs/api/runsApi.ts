import { segment, type HttpClient } from '@/shared/api'
import { createRunEventSource, type RunEventTransport } from './runEventSource'
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
export interface ResumeOptions {
  stage?: Exclude<WorkflowStage, 'finish'>
  checkpoint_id?: string
  request_id?: string
}
export type RecoveryQuery = Pick<ResumeOptions, 'stage' | 'checkpoint_id'>
export function createRunsApi(
  http: HttpClient,
  subscribe: RunEventTransport = createRunEventSource(),
) {
  return {
    subscribe,
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
    resume: (id: string, options: ResumeOptions = {}) =>
      http.request<{ session_id: string }>({
        url: `/sessions/${segment(id)}/resume`,
        method: 'POST',
        data: options,
      }),
    recover: (id: string, options: ResumeOptions = {}) =>
      http.request<{ session_id: string }>({
        url: `/sessions/${segment(id)}/recover`,
        method: 'POST',
        data: options,
      }),
    recovery: (id: string, query: RecoveryQuery = {}, signal?: AbortSignal) =>
      http.request<RecoveryAvailability>({
        url: `/sessions/${segment(id)}/recovery`,
        params: query,
        signal,
      }),
    cancel: (id: string) =>
      http.request<{ session_id: string; cancelled: boolean }>({
        url: `/sessions/${segment(id)}/cancel`,
        method: 'POST',
      }),
  }
}
export type RunsApi = ReturnType<typeof createRunsApi>
