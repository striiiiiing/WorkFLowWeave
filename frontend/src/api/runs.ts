import { request } from './client'
import type {
  SessionRecord,
  PhaseContent,
  StageName,
  ID,
} from '@/types'

export interface ListSessionsParams {
  workflow_id?: ID
  limit?: number
  offset?: number
  after?: string
  before?: string
  exclude_session_id?: ID
}

export interface TriggerResponse {
  session_id: ID
}

export const runsApi = {
  // 触发运行
  triggerWorkflow: (workflowId: ID) =>
    request<TriggerResponse>(`/api/workflows/${workflowId}/trigger`, {
      method: 'POST',
    }),

  // 查询 Session 列表
  listSessions: (params: ListSessionsParams = {}) => {
    const query = new URLSearchParams()
    if (params.workflow_id) query.set('workflow_id', params.workflow_id)
    if (params.limit !== undefined) query.set('limit', String(params.limit))
    if (params.offset !== undefined) query.set('offset', String(params.offset))
    if (params.after) query.set('after', params.after)
    if (params.before) query.set('before', params.before)
    if (params.exclude_session_id) query.set('exclude_session_id', params.exclude_session_id)
    
    const qs = query.toString()
    return request<SessionRecord[]>(`/api/runs${qs ? `?${qs}` : ''}`)
  },

  // 查询 Session 详情
  getSession: (sessionId: ID, version?: number) => {
    const qs = version ? `?version=${version}` : ''
    return request<SessionRecord>(`/api/runs/${sessionId}${qs}`)
  },

  // 查询各阶段正文
  getPhaseContent: (sessionId: ID, stage: StageName, version: number) =>
    request<PhaseContent>(`/api/runs/${sessionId}/phases/${stage}?version=${version}`),

  // 取消活动任务
  cancelRun: (sessionId: ID) =>
    request<void>(`/api/runs/${sessionId}/cancel`, {
      method: 'POST',
    }),

  // 从断点恢复执行
  recoverRun: (sessionId: ID) =>
    request<TriggerResponse>(`/api/runs/${sessionId}/recover`, {
      method: 'POST',
    }),
}
