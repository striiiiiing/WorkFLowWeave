import type {
  AgentSession,
  AgentEvent,
  AgentTool,
  AgentFile,
  AgentModel,
  AgentConfig,
  AgentSettings,
  TurnAccepted,
} from '../model/types'
import { segment, type HttpClient } from '@/shared/api'

export function createAgentsApi(http: HttpClient) {
  const sessionPath = (id: string) => `/agents/sessions/${segment(id)}`
  type AgentAction =
    'message' | 'new' | 'resume' | 'stop' | 'append' | 'compact' | 'fork' | 'workflow'
  interface AgentCommandResult<T = unknown> {
    kind: 'session' | 'turn' | 'workflows'
    priority: string
    result: T
  }
  const commandRequest = <T>(payload: {
    action: AgentAction
    session?: string | null
    text?: string
    request_id?: string
    model?: string
    workflow_session_id?: string
    workflow_id?: string
    turn_id?: string
    message_id?: string
  }) =>
    http.request<AgentCommandResult<T>>({
      url: '/channels/web/commands',
      method: 'POST',
      data: { channel: 'web', request_id: crypto.randomUUID(), text: '', ...payload },
    })
  return {
    list: (signal?: AbortSignal) =>
      http.request<AgentSession[]>({ url: '/agents/sessions', signal }),
    create: async (payload: {
      model?: string
      workflow_session_id?: string
      workflow_id?: string
    }) =>
      (
        await commandRequest<AgentSession>({
          action: payload.workflow_session_id || payload.workflow_id ? 'workflow' : 'new',
          ...payload,
        })
      ).result,
    get: (id: string, signal?: AbortSignal) =>
      http.request<AgentSession>({ url: sessionPath(id), signal }),
    history: (id: string, signal?: AbortSignal) =>
      http.request<AgentEvent[]>({ url: `${sessionPath(id)}/history`, signal }),
    source: (id: string, signal?: AbortSignal) =>
      http.request<{
        workflow_session_id: string | null
        input: unknown
        created_at: string
      }>({ url: `${sessionPath(id)}/source`, signal }),
    models: (signal?: AbortSignal) => http.request<AgentModel[]>({ url: '/agents/models', signal }),
    setModel: (id: string, model: string) =>
      http.request<AgentSession>({ url: sessionPath(id), method: 'PATCH', data: { model } }),
    send: (id: string, requestId: string, text: string) =>
      commandRequest<TurnAccepted>({
        action: 'message',
        session: id,
        request_id: requestId,
        text,
      }).then((response) => response.result),
    command: (id: string | null, text: string, requestId: string, model?: string) =>
      http.request<{
        kind: 'session' | 'turn' | 'workflows'
        priority: string
        result: AgentSession | TurnAccepted | unknown[]
      }>({
        url: '/channels/web/commands',
        method: 'POST',
        data: {
          channel: 'web',
          session: id,
          text,
          request_id: requestId,
          ...(!text.trim().startsWith('/') ? { action: 'message' as const } : {}),
          ...(model ? { model } : {}),
        },
      }),
    append: (id: string, requestId: string, text: string) =>
      commandRequest<TurnAccepted>({
        action: 'append',
        session: id,
        request_id: requestId,
        text,
      }).then((response) => response.result),
    fork: async (
      id: string,
      payload: { turn_id?: string; model?: string; message_id?: string } = {},
    ) => (await commandRequest<AgentSession>({ action: 'fork', session: id, ...payload })).result,
    cancel: async (id: string) =>
      (await commandRequest<AgentSession>({ action: 'stop', session: id })).result,
    compact: async (id: string) =>
      (await commandRequest<TurnAccepted>({ action: 'compact', session: id })).result,
    tools: (signal?: AbortSignal) => http.request<AgentTool[]>({ url: '/agents/tools', signal }),
    updateTool: (pluginId: string, enabled: boolean) =>
      http.request({ url: `/agents/tools/${segment(pluginId)}`, method: 'PUT', data: { enabled } }),
    config: (signal?: AbortSignal) =>
      http.request<AgentSettings>({ url: '/agents/config', signal }),
    updateConfig: (config: AgentConfig) =>
      http.request<AgentConfig>({ url: '/agents/config', method: 'PUT', data: config }),
    readFile: (id: string, path: string, offset = 0, limit = 200, signal?: AbortSignal) =>
      http.request<AgentFile>({
        url: '/agents/file',
        params: { session_id: id, path, offset, limit },
        signal,
      }),
    writeFile: (id: string, path: string, content: string, hash: string) =>
      http.request<{ hash: string }>({
        url: '/agents/file',
        params: { session_id: id, path },
        method: 'PUT',
        data: { mode: 'overwrite', content },
        headers: hash === '*' ? { 'If-None-Match': '*' } : { 'If-Match': `"${hash}"` },
      }),
  }
}
export type AgentsApi = ReturnType<typeof createAgentsApi>
