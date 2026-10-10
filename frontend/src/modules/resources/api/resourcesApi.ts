import { segment, type HttpClient } from '@/shared/api'
import type { JsonObject } from '@/shared/types'
import type {
  Credential,
  MCPServerConfig,
  ResourceKind,
  ResourceMap,
  SourceConfig,
  SourceOverride,
  AIConfig,
  FileCall,
} from '../model/public'
import type { McpConfig } from '../model/mcp/import'

export function createResourcesApi(http: HttpClient) {
  return {
    createTextReference: (path: string, text: string) =>
      http.request<FileCall>({
        url: '/collection/files/text',
        method: 'POST',
        data: { path, file_type: 'text', text },
      }),
    importTextReference: (path: string, file: File) =>
      http.request<FileCall>({
        url: '/collection/files/import',
        method: 'POST',
        params: { path, file_type: 'text' },
        headers: { 'Content-Type': 'application/octet-stream' },
        data: file,
      }),
    startChannelConnection: (id: string) =>
      http.request<ChannelConnectionStatus>({
        url: `/channels/${segment(id)}/connection`,
        method: 'POST',
      }),
    channelConnection: (id: string) =>
      http.request<ChannelConnectionStatus>({ url: `/channels/${segment(id)}/connection` }),
    cancelChannelConnection: (id: string) =>
      http.request<ChannelConnectionStatus>({
        url: `/channels/${segment(id)}/connection`,
        method: 'DELETE',
      }),
    startChannelLogin: (capability: string, options: JsonObject) =>
      http.request<ChannelLoginStatus>({
        url: `/channels/login/${segment(capability)}`,
        method: 'POST',
        data: { options },
      }),
    channelLoginStatus: (id: string) =>
      http.request<ChannelLoginStatus>({ url: `/channels/login/sessions/${segment(id)}` }),
    verifyChannelLogin: (id: string, code: string) =>
      http.request<ChannelLoginStatus>({
        url: `/channels/login/sessions/${segment(id)}/verify`,
        method: 'POST',
        data: { code },
      }),
    cancelChannelLogin: (id: string) =>
      http.request<void>({ url: `/channels/login/sessions/${segment(id)}`, method: 'DELETE' }),
    channelConversation: (id: string, signal?: AbortSignal) =>
      http.request<ChannelConversation>({
        url: `/channels/${segment(id)}/conversation`,
        signal,
      }),
    bindChannelConversation: (id: string, sessionId: string | null) =>
      http.request<ChannelConversation>({
        url: `/channels/${segment(id)}/conversation`,
        method: 'PUT',
        data: { session_id: sessionId },
      }),
    conversationOptions: (signal?: AbortSignal) =>
      http.request<ConversationOption[]>({ url: '/agents/sessions', signal }),
    resolveSource: (id: string, override?: SourceOverride, signal?: AbortSignal) =>
      http.request<SourceConfig>({
        url: `/sources/${segment(id)}/resolve`,
        method: 'POST',
        data: override ?? {},
        signal,
      }),
    mcpStatus: (signal?: AbortSignal) =>
      http.request<MCPServerStatus[]>({ url: '/mcp/catalog/status', signal }),
    probeMcpServer: (server: string) =>
      http.request<MCPHealthReport>({
        url: `/mcp_servers/${segment(server)}/probe`,
        method: 'POST',
      }),
    mcpCatalog: (server?: string, query = '', cursor = 0) =>
      http.request<MCPToolCatalog>({
        url: '/mcp/catalog',
        params: { server, query, cursor, page_size: 100 },
      }),
    loadMcpCatalog: (server: string, refresh = false) =>
      http.request<{ server: string; tool_count: number }>({
        url: `/mcp/catalog/${segment(server)}/load`,
        method: 'POST',
        params: { refresh },
      }),
    describeMcpTool: (server: string, tool: string) =>
      http.request<MCPToolDescription>({
        url: `/mcp/catalog/${segment(server)}/tools/${segment(tool)}`,
      }),
    discoverAIModels: (config: AIConfig) =>
      http.request<string[]>({
        url: '/ai/discover-models',
        method: 'POST',
        data: config,
      }),
    protectCredential: (plaintext: string) =>
      http.request<Extract<Credential, { kind: 'encrypted' }>>({
        url: '/credentials/protect',
        method: 'POST',
        data: { plaintext },
      }),
    list: <K extends ResourceKind>(kind: K, signal?: AbortSignal) =>
      http.request<ResourceMap[K][]>({ url: `/${kind}`, signal }),
    get: <K extends ResourceKind>(kind: K, id: string, signal?: AbortSignal) =>
      http.request<ResourceMap[K]>({ url: `/${kind}/${segment(id)}`, signal }),
    create: <K extends ResourceKind>(kind: K, value: ResourceMap[K]) =>
      http.request<ResourceMap[K]>({ url: `/${kind}`, method: 'POST', data: value }),
    importMcpServers: (value: McpConfig) =>
      http.request<MCPServerConfig[]>({ url: '/mcp_servers/import', method: 'POST', data: value }),
    replace: <K extends ResourceKind>(kind: K, id: string, value: ResourceMap[K]) =>
      http.request<ResourceMap[K]>({ url: `/${kind}/${segment(id)}`, method: 'PUT', data: value }),
    delete: (kind: ResourceKind, id: string) =>
      http.request<void>({ url: `/${kind}/${segment(id)}`, method: 'DELETE' }),
  }
}
export interface ChannelConversation {
  session_id: string | null
}
export interface ChannelConnectionStatus {
  channel_id: string
  state: 'idle' | 'connecting' | 'waiting_message' | 'connected' | 'failed' | 'cancelled'
  message: string
  error: { code: string; message: string; details: Record<string, unknown> } | null
  target_options: JsonObject
}
export interface ChannelLoginStatus {
  session_id: string
  state: 'waiting' | 'scanned' | 'verify_required' | 'connected' | 'failed'
  qr_url: string | null
  qr_image: string | null
  account_id: string | null
  message: string
  options: JsonObject
}
export interface ConversationOption {
  session_id: string
  title: string
  status: string
}
export interface MCPServerStatus {
  server: string
  state: 'unloaded' | 'cached' | 'connected' | 'failed'
  enabled: boolean
  error: string | null
  version: string
  health: MCPHealthReport
}
export interface MCPHealthReport {
  server: string
  status: 'unknown' | 'healthy' | 'unhealthy' | 'disabled'
  checked_at: string | null
  latency_ms: number | null
  tool_count: number | null
  error: { code: string; message: string; details: Record<string, unknown> } | null
}
export interface MCPToolCatalog {
  entries: { server: string; tool: string; description: string }[]
  next_cursor: number | null
  incomplete: boolean
  load_servers: string[]
  servers: MCPServerStatus[]
}
export interface MCPToolDescription {
  name: string
  description?: string
  inputSchema: JsonObject
}
export type ResourcesApi = ReturnType<typeof createResourcesApi>
