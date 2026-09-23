import { request, segment } from './client'

export interface ContextBudget {
  messages: number
  system: number
  tools: number
  output: number
  total: number
  window: number
  trigger?: number
  remaining: number
  estimated: boolean
  token_counter: string
}
export interface AgentSession {
  session_id: string
  branch_id: string
  model: string | null
  workflow_session_id: string | null
  created_at: string
  updated_at: string
  status: string
  turn_id: string | null
  parent_session_id?: string | null
  parent_turn_id?: string | null
  parent_branch_id?: string | null
  parent_event_id?: number | null
  context_budget: ContextBudget | null
  continuable: boolean
  history_path: string
  last_checkpoint_at: string | null
  continuation_error?: { code: string; message: string } | null
  active_resources?: { model: string | null; tools_generation: number | null } | null
}
export interface AgentEvent {
  id: number
  session_id: string
  turn_id: string | null
  type: string
  at: string
  data: Record<string, unknown>
}
export interface AgentTool {
  name: string
  description: string
  execution: 'read' | 'exclusive' | null
  input_schema: Record<string, unknown> | null
  enabled: boolean
  registered?: boolean
  plugin: string
  generation: number | null
  definition_tokens: number
}
export interface AgentFile {
  path: string
  kind: 'file' | 'directory'
  content?: string
  hash?: string
  readonly: boolean
  offset: number
  next_offset: number | null
  total_lines?: number
  entries?: Array<{ name: string; kind: 'file' | 'directory'; readonly: boolean; symlink: boolean }>
}
export interface AgentModel {
  reference: string
  provider: string
  ai: string
  model: string
}
export interface AgentConfig {
  context_window: number | null
  output_tokens: number
  trigger_tokens: number
  keep_tokens: number
  summary_ai: string | null
  summary_context_window: number | null
  summary_max_tokens: number
  summary_prompt: string
  timezone: string
  sandbox: { enabled: boolean; network: boolean }
  idle_timeout: number
  read_concurrency: number
  [key: string]: unknown
}
export interface AgentSettings {
  config: AgentConfig
  models: AgentModel[]
  tools: AgentTool[]
  scheduler: Record<string, number>
  sandbox: { enabled: boolean; network: boolean; available: boolean; status: string }
  readonly_paths: string[]
}
export interface TurnAccepted {
  turn_id: string
  session_id: string
  deduplicated: boolean
  status?: string
}
const sessionPath = (id: string) => `/agents/sessions/${segment(id)}`
export const agentsApi = {
  list: (signal?: AbortSignal) => request<AgentSession[]>('/agents/sessions', { signal }),
  create: (payload: { model?: string; workflow_session_id?: string; workflow_id?: string }) =>
    request<AgentSession>('/agents/sessions', { method: 'POST', body: JSON.stringify(payload) }),
  get: (id: string, signal?: AbortSignal) => request<AgentSession>(sessionPath(id), { signal }),
  history: (id: string, signal?: AbortSignal) =>
    request<AgentEvent[]>(`${sessionPath(id)}/history`, { signal }),
  source: (id: string, signal?: AbortSignal) =>
    request<{
      workflow_session_id: string | null
      input: unknown
      created_at: string
    }>(`${sessionPath(id)}/source`, { signal }),
  models: (signal?: AbortSignal) => request<AgentModel[]>('/agents/models', { signal }),
  setModel: (id: string, model: string) =>
    request<AgentSession>(sessionPath(id), {
      method: 'PATCH',
      body: JSON.stringify({ model }),
    }),
  send: (id: string, requestId: string, text: string) =>
    request<TurnAccepted>(`${sessionPath(id)}/messages`, {
      method: 'POST',
      body: JSON.stringify({ request_id: requestId, text }),
    }),
  command: (id: string | null, text: string, requestId: string, model?: string) =>
    request<{
      kind: 'session' | 'turn' | 'workflows'
      priority: string
      result: AgentSession | TurnAccepted | unknown[]
    }>('/agents/commands', {
      method: 'POST',
      body: JSON.stringify({
        channel: 'web',
        session: id,
        text,
        request_id: requestId,
        ...(model ? { model } : {}),
      }),
    }),
  append: (id: string, requestId: string, text: string) =>
    request<TurnAccepted>(`${sessionPath(id)}/append`, {
      method: 'POST',
      body: JSON.stringify({ request_id: requestId, text }),
    }),
  fork: (id: string, payload: { turn_id?: string; model?: string; message_id?: string } = {}) =>
    request<AgentSession>(`${sessionPath(id)}/fork`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  cancel: (id: string) => request<AgentSession>(`${sessionPath(id)}/cancel`, { method: 'POST' }),
  compact: (id: string) => request<TurnAccepted>(`${sessionPath(id)}/compact`, { method: 'POST' }),
  tools: (signal?: AbortSignal) => request<AgentTool[]>('/agents/tools', { signal }),
  updateTool: (pluginId: string, enabled: boolean) =>
    request(`/agents/tools/${segment(pluginId)}`, {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    }),
  config: (signal?: AbortSignal) => request<AgentSettings>('/agents/config', { signal }),
  updateConfig: (config: AgentConfig) =>
    request<AgentConfig>('/agents/config', {
      method: 'PUT',
      body: JSON.stringify(config),
    }),
  readFile: (id: string, path: string, offset = 0, limit = 200, signal?: AbortSignal) =>
    request<AgentFile>(
      `/agents/file?session_id=${segment(id)}&path=${encodeURIComponent(path)}&offset=${offset}&limit=${limit}`,
      { signal },
    ),
  writeFile: (id: string, path: string, content: string, hash: string) =>
    request<{ hash: string }>(
      `/agents/file?session_id=${segment(id)}&path=${encodeURIComponent(path)}`,
      {
        method: 'PUT',
        body: JSON.stringify({ mode: 'overwrite', content }),
        headers: hash === '*' ? { 'If-None-Match': '*' } : { 'If-Match': `"${hash}"` },
      },
    ),
}
