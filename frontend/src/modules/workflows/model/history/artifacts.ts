import type { ArtifactAvailability, SessionRecord } from '../shared/types'

export interface SessionQuery {
  workflow_id?: string
  workflow_name?: string
  session_id?: string
  status?: SessionRecord['status']
  limit?: number
  offset?: number
  after?: string
  before?: string
}

export const availabilityLabels: Record<ArtifactAvailability, string> = {
  available: '可读取',
  pending: '尚未生成',
  not_saved: '未保存',
  expired: '已过期',
  missing: '文件缺失',
  corrupt: '文件损坏',
  write_failed: '写入失败',
}

export function unavailableText(value: ArtifactAvailability, active: boolean): string {
  const labels: Record<ArtifactAvailability, string> = {
    available: '',
    pending: active ? '此阶段尚未产生结果。' : '本次运行没有此阶段的结果记录。',
    not_saved: '本次运行未保存此阶段的正文，无法查看报告。',
    expired: '此阶段的正文已过期，无法查看报告。',
    missing: '此阶段的正文文件缺失。',
    corrupt: '此阶段的正文文件损坏，无法读取。',
    write_failed: '此阶段的正文保存失败。',
  }
  return labels[value]
}
