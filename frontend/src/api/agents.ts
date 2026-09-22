import { request, segment } from './client'

export interface AgentSession {
  session_id: string
  branch_id: string
  model: string | null
  workflow_session_id: string | null
  created_at: string
  updated_at: string
  status: string
  turn_id: string | null
}

export interface AgentEvent {
  id: number
  type: string
  created_at: string
  [key: string]: unknown
}

export interface AgentTool {
  name: string
  description: string
  execution: 'read' | 'exclusive'
  input_schema: Record<string, unknown>
  enabled: boolean
  plugin?: string
  generation?: number | null
  definition_tokens?: number
}

export const agentsApi = {
  list: (signal?: AbortSignal) => request<AgentSession[]>('/agents/sessions', { signal }),
  create: (payload: { model?: string; workflow_session_id?: string; workflow_result?: unknown }) =>
    request<AgentSession>('/agents/sessions', { method: 'POST', body: JSON.stringify(payload) }),
  get: (id: string, signal?: AbortSignal) => request<AgentSession>(`/agents/sessions/${segment(id)}`, { signal }),
  send: (id: string, requestId: string, text: string) =>
    request<{ turn_id: string; session_id: string; deduplicated: boolean }>(
      `/agents/sessions/${segment(id)}/messages`,
      { method: 'POST', body: JSON.stringify({ request_id: requestId, text }) },
    ),
  cancel: (id: string) => request<AgentSession>(`/agents/sessions/${segment(id)}/cancel`, { method: 'POST' }),
  compact: (id: string) => request<{ status: string; event_id: number }>(
    `/agents/sessions/${segment(id)}/compact`, { method: 'POST' },
  ),
  tools: (signal?: AbortSignal) => request<AgentTool[]>('/agents/tools', { signal }),
  config: (signal?: AbortSignal) => request<{
    config: Record<string, unknown>
    tools: AgentTool[]
    scheduler: Record<string, number>
    sandbox: { enabled: boolean; network: boolean; available: boolean; status: string }
  }>('/agents/config', { signal }),
  readFile: (sessionId: string, path: string, signal?: AbortSignal) =>
    request<Record<string, unknown>>(`/agents/file?session_id=${segment(sessionId)}&path=${encodeURIComponent(path)}`, { signal }),
  writeFile: (sessionId: string, path: string, payload: {
    mode: 'overwrite' | 'append' | 'replace'
    content: string
    old_text?: string
    expected_hash?: string
  }, signal?: AbortSignal) =>
    request<Record<string, unknown>>(`/agents/file?session_id=${segment(sessionId)}&path=${encodeURIComponent(path)}`, {
      method: 'PUT', body: JSON.stringify(payload), signal,
    }),
}
