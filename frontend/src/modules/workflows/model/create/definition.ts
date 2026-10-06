import type { CollectionConfig } from './stages/collection'
import type { AnalysisConfig } from './stages/analysis'
import type { FanInConfig } from './stages/aggregation'
import type { NotificationConfig } from './stages/notification'
import type { BackupPolicy } from './backup'

export type WorkflowSchedule =
  | { type: 'at'; at: string }
  | { type: 'every'; every_seconds: number }
  | { type: 'cron'; expression: string; timezone: string | null }

export interface WorkflowDefinition extends CollectionConfig, AnalysisConfig, NotificationConfig {
  id: string
  name: string
  fan_in: FanInConfig | null
  system_prompt: string
  input_prompt: string
  schedule: WorkflowSchedule | null
  enabled: boolean
  backup: BackupPolicy
}
