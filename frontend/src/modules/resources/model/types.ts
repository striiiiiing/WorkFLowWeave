import type { ErrorInfo, JsonObject } from '@/shared/types'

export type SourcePolicy = 'stop' | 'notice' | 'skip'
export interface SourceConfig {
  id: string
  display_name?: string | null
  description?: string
  collector: string
  enabled: boolean
  options: JsonObject
  setters: JsonObject
  template: string | null
  timeout: number
  on_error: SourcePolicy
  on_missing: SourcePolicy
  on_empty: SourcePolicy
  on_filtered_empty: SourcePolicy
}
export interface SetterTemplate {
  id: string
  collector: string
  setters: JsonObject
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

export interface AIModelTestResult {
  task_id: string
  status: 'success' | 'failed' | 'timeout' | 'cancelled'
  text: string
  error: ErrorInfo | null
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
  options: JsonObject
  setters: JsonObject
  template: string | null
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
  setters: SetterTemplate
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
  Pick<SourceConfig, 'timeout' | 'on_error' | 'on_missing' | 'on_empty' | 'on_filtered_empty'>
>
