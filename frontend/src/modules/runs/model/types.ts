import type { ErrorInfo, JsonValue } from '@/shared/types'

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
