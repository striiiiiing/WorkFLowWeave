import type { SourcePolicy, SourceOverride, ChannelOverride } from '@/modules/resources/public'

export type ContinuePolicy = 'stop' | 'continue'
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
  cron: string | null
  cron_timezone: string
  enabled: boolean
  backup: BackupPolicy
}
