import type { JsonObject } from '@/shared/types'

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
export interface ResourceMap {
  sources: SourceConfig
  setters: SetterTemplate
  ai: AIConfig
  channels: ChannelConfig
}
export type ResourceKind = keyof ResourceMap
