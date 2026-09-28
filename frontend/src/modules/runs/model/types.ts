import type { ErrorInfo, JsonValue } from '@/shared/types'

export type WorkflowStage = 'collect' | 'analyze' | 'aggregate' | 'notify' | 'finish'
export type SessionStatus =
  'created' | 'running' | 'completed' | 'partial' | 'failed' | 'cancelled' | 'interrupted'
export type WorkflowProgressEvent = 'item' | 'aggregate' | 'delivery' | 'lifecycle'
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
export interface WorkflowProgress {
  session_id: string
  execution_epoch: string | null
  stage: WorkflowStage | null
  event: WorkflowProgressEvent
  status: string
  item_id: string | null
  output_id: string | null
  channel_id: string | null
  label: string | null
  result_ref: string | null
  version: number | null
  availability: ArtifactAvailability
  error: ErrorInfo | null
  summary: Record<string, JsonValue>
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
  execution_epoch: string | null
  progress: WorkflowProgress[]
}
export interface RecoveryAvailability {
  available: boolean
  reason: ErrorInfo | null
}
export type ReportSection =
  | { kind: 'text'; title: string; text: string }
  | {
      kind: 'metrics'
      title: string
      items: { label: string; value: string | number; unit: string }[]
    }
  | {
      kind: 'table'
      title: string
      columns: string[]
      rows: (string | number | boolean | null)[][]
    }
