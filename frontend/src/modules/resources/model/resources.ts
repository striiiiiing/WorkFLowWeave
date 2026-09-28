import type { AIConfig, ChannelConfig, MCPServerConfig, SourceConfig } from './types'
import type { JsonObject } from '@/shared/types'
export type EditableKind = 'sources' | 'mcp_servers' | 'ai' | 'channels'
export type EditableResource = SourceConfig | MCPServerConfig | AIConfig | ChannelConfig
export const resourceNames: Record<EditableKind, string> = {
  sources: '数据源',
  mcp_servers: 'MCP 服务',
  ai: '供应商渠道',
  channels: '通知渠道',
}
export const resourceKinds = [
  { key: 'sources', label: '数据源', icon: 'database' },
  { key: 'mcp_servers', label: 'MCP 服务', icon: 'database' },
  { key: 'ai', label: '供应商渠道', icon: 'bot' },
  { key: 'channels', label: '通知渠道', icon: 'mail' },
] as const

export function generatedResourceId(prefix?: string | null): string {
  const suffix = crypto.randomUUID()
  return prefix ? `${prefix}_${suffix}` : suffix
}

export function credentialPropertyNames(schema: JsonObject | undefined): string[] {
  const properties = (schema?.properties ?? {}) as Record<string, JsonObject>
  return Object.keys(properties).filter(
    (name) => properties[name]['x-logagent-credential'] === true,
  )
}

// Initial values follow the backend models, including the AI execution budget.
export function createResource(kind: EditableKind): EditableResource {
  const factories = {
    sources: (): SourceConfig => ({
      id: crypto.randomUUID(),
      call: { kind: 'mcp', server: '', tool: '', arguments: {} },
      display_name: '',
      description: '',
      enabled: true,
      limits: { item_tokens: null, field_tokens: null },
      timeout: 60,
      on_error: 'notice',
      on_missing: 'notice',
      on_empty: 'notice',
    }),
    mcp_servers: (): MCPServerConfig => ({
      id: crypto.randomUUID(),
      transport: 'stdio',
      enabled: true,
      command: '',
      args: [],
      cwd: null,
      url: null,
      env: {},
      headers: {},
      timeout: 60,
    }),
    ai: (): AIConfig => ({
      id: crypto.randomUUID(),
      provider: 'openai_compatible_api',
      base_url: null,
      api_key: null,
      system_prompt: '',
      models: {},
      timeout: 600,
      retries: 5,
    }),
    channels: (): ChannelConfig => ({
      id: crypto.randomUUID(),
      channel: '',
      options: {},
      timeout: 30,
      enabled: true,
      agent_enabled: false,
    }),
  }
  return factories[kind]()
}

export function sourceName(source: SourceConfig): string {
  return source.display_name || source.id
}
