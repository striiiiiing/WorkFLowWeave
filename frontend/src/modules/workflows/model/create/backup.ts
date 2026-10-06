import type { ContinuePolicy } from './policies'

export interface BackupPolicy {
  enabled: boolean
  snapshot: boolean
  collection: boolean
  analysis: boolean
  final: boolean
  on_failure: ContinuePolicy
  checkpoint_retention_days: number | null
  collection_retention_days: number | null
  analysis_retention_days: number | null
  final_retention_days: number | null
  /** Present only in configurations saved before classified retention. */
  retention_days?: number | null
}

export function createBackupPolicy(): BackupPolicy {
  return {
    enabled: true,
    snapshot: true,
    collection: true,
    analysis: true,
    final: true,
    on_failure: 'stop',
    checkpoint_retention_days: null,
    collection_retention_days: null,
    analysis_retention_days: null,
    final_retention_days: null,
  }
}

export const retentionFields = [
  { key: 'checkpoint_retention_days', label: 'Checkpoint 保留天数' },
  { key: 'collection_retention_days', label: '采集正文保留天数' },
  { key: 'analysis_retention_days', label: '分析正文保留天数' },
  { key: 'final_retention_days', label: '最终正文保留天数' },
] as const

export function hasLegacyRetention(policy: BackupPolicy): boolean {
  return Object.prototype.hasOwnProperty.call(policy, 'retention_days')
}

export function classifyLegacyRetention(policy: BackupPolicy): BackupPolicy {
  const { retention_days: _legacy, ...current } = policy
  return {
    ...current,
    checkpoint_retention_days: current.checkpoint_retention_days ?? null,
    collection_retention_days: current.collection_retention_days ?? null,
    analysis_retention_days: current.analysis_retention_days ?? null,
    final_retention_days: current.final_retention_days ?? null,
  }
}
