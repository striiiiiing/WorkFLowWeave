import type { ErrorInfo } from '@/shared/types'
import type { WorkflowStage } from '../shared/types'

export interface RecoveryAvailability {
  available: boolean
  reason: ErrorInfo | null
}

export interface ResumeOptions {
  stage?: Exclude<WorkflowStage, 'finish'> | 'process'
  checkpoint_id?: string
  request_id?: string
}

export type RecoveryQuery = Pick<ResumeOptions, 'stage' | 'checkpoint_id'>
