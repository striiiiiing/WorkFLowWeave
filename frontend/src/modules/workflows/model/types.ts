import type { SourcePolicy, SourceOverride, ChannelOverride } from '@/modules/resources/public'

export type ContinuePolicy = 'stop' | 'continue'
export interface AnalysisTask {
  id: string
  ai: string
  system_prompt: string | null
  input_prompt: string | null
  user_prompt: string
  model: string
}
export interface FanInConfig {
  order: string[]
  separator: string
  ai: string | null
  system_prompt: string | null
  input_prompt: string | null
  user_prompt: string
  reuse_from: string | null
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
export type WorkflowSchedule =
  | { type: 'at'; at: string }
  | { type: 'every'; every_seconds: number }
  | { type: 'cron'; expression: string; timezone: string | null }

export interface WorkflowDefinition {
  id: string
  name: string
  sources: string[]
  analyses: AnalysisTask[]
  fan_in: FanInConfig | null
  system_prompt: string
  input_prompt: string
  channels: string[]
  source_overrides: Record<string, SourceOverride>
  channel_overrides: Record<string, ChannelOverride>
  input_separator: string
  input_processing: {
    format: 'none' | 'ison' | 'toon' | 'zon' | 'md' | 'csv'
    total_tokens: number | null
    item_tokens: number | null
    field_tokens: number | null
  }
  collection_concurrency: number
  analysis_concurrency: number
  on_all_empty: SourcePolicy
  analysis_failure: ContinuePolicy
  send_partial: boolean
  schedule: WorkflowSchedule | null
  enabled: boolean
  backup: BackupPolicy
}
