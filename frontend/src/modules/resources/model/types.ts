import type { JsonObject } from '@/shared/types'

export type SourcePolicy = 'stop' | 'notice' | 'skip'
export interface SourceLimits {
  item_tokens: number | null
  field_tokens: number | null
}
export type SourceCall =
  | { kind: 'mcp'; server: string; tool: string; arguments: JsonObject }
  | { kind: 'cli'; mode: 'argv'; executable: string; argv: string[]; cwd: string | null }
  | { kind: 'cli'; mode: 'shell'; command: string; cwd: string | null }
export interface SourceConfig {
  id: string
  display_name?: string | null
  description?: string
  collector?: string | null
  call: SourceCall | null
  options?: JsonObject
  setters?: JsonObject
  template?: string | null
  enabled: boolean
  limits: SourceLimits
  timeout: number
  on_error: SourcePolicy
  on_missing: SourcePolicy
  on_empty: SourcePolicy
}
export interface MCPServerConfig {
  id: string
  transport: 'stdio' | 'streamable_http' | 'sse'
  enabled: boolean
  health_check_enabled: boolean
  health_check_interval_minutes: number
  command: string | null
  args: string[]
  cwd: string | null
  url: string | null
  env: Record<string, Credential>
  headers: Record<string, Credential>
  timeout: number
}
export type Credential =
  | { kind: 'env'; name: string }
  | { kind: 'encrypted'; format_version: number; key_id: string; ciphertext: string }
export interface AIConfig {
  id: string
  provider: string
  base_url: string | null
  api_key: Credential | null
  system_prompt: string
  models: Record<string, JsonObject>
  timeout: number
  retries: number
}

export interface ChannelConfig {
  id: string
  channel: string
  options: JsonObject
  timeout: number
  enabled: boolean
  agent_enabled?: boolean
}
export interface SourceOverride {
  source?: SourceConfig | null
  arguments?: JsonObject | null
  limits?: SourceLimits
}
export interface ChannelOverride {
  options: JsonObject
}

/** Resource editors never decide where a value is persisted. */
export type SourceSaveTarget =
  | { kind: 'shared-resource'; resourceId: string }
  | { kind: 'workflow-draft'; workflowId: string; sourceId: string }

export interface SourceUsageView {
  id: string
  name: string
  detached: boolean
}

export interface SourceConfigEditorGateway {
  resolve(sourceId: string, override?: SourceOverride, signal?: AbortSignal): Promise<SourceConfig>
  save(target: SourceSaveTarget, value: SourceConfig): Promise<void>
}
export interface ResourceMap {
  sources: SourceConfig
  mcp_servers: MCPServerConfig
  ai: AIConfig
  channels: ChannelConfig
}
export type ResourceKind = keyof ResourceMap

export type CredentialProtector = (
  plaintext: string,
) => Promise<Extract<Credential, { kind: 'encrypted' }>>

export type SourceBasicChanges = Partial<
  Pick<SourceConfig, 'display_name' | 'description' | 'enabled'>
>
export type SourceAdvancedChanges = Partial<
  Pick<SourceConfig, 'timeout' | 'on_error' | 'on_missing' | 'on_empty' | 'limits'>
>
