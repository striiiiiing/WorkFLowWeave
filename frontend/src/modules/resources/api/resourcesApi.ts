import { segment, type HttpClient } from '@/shared/api'
import type { JsonObject } from '@/shared/types'
import type {
  Credential,
  ResourceKind,
  ResourceMap,
  SourceConfig,
  SourceOverride,
  AIConfig,
} from '../model/types'

export function createResourcesApi(http: HttpClient) {
  return {
    resolveSource: (id: string, override?: SourceOverride, signal?: AbortSignal) =>
      http.request<SourceConfig>({
        url: `/sources/${segment(id)}/resolve`,
        method: 'POST',
        data: override ?? {},
        signal,
      }),
    mcpStatus: () => http.request<MCPServerStatus[]>({ url: '/mcp/catalog/status' }),
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
    replace: <K extends ResourceKind>(kind: K, id: string, value: ResourceMap[K]) =>
      http.request<ResourceMap[K]>({ url: `/${kind}/${segment(id)}`, method: 'PUT', data: value }),
    delete: (kind: ResourceKind, id: string) =>
      http.request<void>({ url: `/${kind}/${segment(id)}`, method: 'DELETE' }),
  }
}
export interface MCPServerStatus {
  server: string
  state: 'unloaded' | 'cached' | 'connected' | 'failed'
  enabled: boolean
  error: string | null
  version: string
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
