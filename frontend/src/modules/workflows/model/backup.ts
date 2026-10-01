import type { BackupPolicy } from './types'

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
