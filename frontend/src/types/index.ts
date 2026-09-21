// HTTP DTOs mirror src/logagent/models.py; server validation remains authoritative.
export type JsonValue = string | number | boolean | null | JsonValue[] | JsonObject
export interface JsonObject {
  [key: string]: JsonValue
}
export interface ErrorInfo {
  code: string
  message: string
  details: JsonObject
}
export type SourcePolicy = 'stop' | 'notice' | 'skip'
export type ContinuePolicy = 'stop' | 'continue'
export interface SourceConfig {
  id: string
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
}
export interface AnalysisTask {
  id: string
  ai: string
  prompt: string
  model: string
}
export interface FanInConfig {
  order: string[]
  separator: string
  ai: string | null
  prompt: string
  model: string | null
  mark_incomplete: boolean
}
export interface BackupPolicy {
  enabled: boolean
  snapshot: boolean
  collection: boolean
  analysis: boolean
  final: boolean
  on_failure: ContinuePolicy
  retention_days: number | null
}
export interface SourceOverride {
  options: JsonObject
  setters: JsonObject
  template: string | null
}
export interface ChannelOverride {
  options: JsonObject
}
export interface WorkflowDefinition {
  id: string
  name: string
  sources: string[]
  analyses: AnalysisTask[]
  fan_in: FanInConfig | null
  channels: string[]
  source_overrides: Record<string, SourceOverride>
  channel_overrides: Record<string, ChannelOverride>
  input_separator: string
  include_counts: boolean
  collection_concurrency: number
  analysis_concurrency: number
  on_all_empty: SourcePolicy
  analysis_failure: ContinuePolicy
  send_partial: boolean
  interval_seconds: number | null
  enabled: boolean
  backup: BackupPolicy
}
export interface ResourceMap {
  sources: SourceConfig
  setters: SetterTemplate
  ai: AIConfig
  channels: ChannelConfig
  workflows: WorkflowDefinition
}
export type ResourceKind = keyof ResourceMap
export type WorkflowStage = 'collect' | 'analyze' | 'aggregate' | 'notify' | 'finish'
export type SessionStatus =
  'created' | 'running' | 'completed' | 'partial' | 'failed' | 'cancelled' | 'interrupted'
export type ArtifactAvailability =
  'available' | 'pending' | 'not_saved' | 'expired' | 'missing' | 'corrupt' | 'write_failed'
export interface ArtifactInfo {
  stage: WorkflowStage
  availability: ArtifactAvailability
  size_bytes: number | null
  error: ErrorInfo | null
}
export interface PhaseContent extends ArtifactInfo {
  session_id: string
  version: number
  content: JsonValue
}
export interface SessionRecord {
  session_id: string
  workflow_id: string
  workflow_name: string | null
  version: number
  status: SessionStatus
  stage: WorkflowStage | null
  created_at: string
  updated_at: string
  finished_at: string | null
  error: ErrorInfo | null
  artifacts: ArtifactInfo[]
  snapshot_availability: ArtifactAvailability
}
export interface CapabilityDescription {
  kind: 'collector' | 'channel'
  name: string
  description: string
  plugin: string
  capabilities: string[]
  options_schema: JsonObject
  setters_schema: JsonObject | null
  fields: string[]
  count_unit: string | null
}
export interface DiscoveryReport {
  registered: CapabilityDescription[]
  errors: ErrorInfo[]
}
export interface ComponentHealth {
  component: string
  status: 'available' | 'degraded' | 'unavailable' | 'unknown'
  required: boolean
  error: ErrorInfo | null
  checked_at: string | null
}
export interface HealthReport {
  status: 'ready' | 'degraded' | 'unavailable'
  accepting_runs: boolean
  checked_at: string
  components: ComponentHealth[]
}
