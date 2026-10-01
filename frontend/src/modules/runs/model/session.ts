import type { SessionStatus, WorkflowStage, ArtifactAvailability } from './types'

export const sessionStates = {
  created: { label: '等待执行', type: 'info', active: true },
  running: { label: '运行中', type: 'primary', active: true },
  completed: { label: '已完成', type: 'success', active: false },
  partial: { label: '部分完成', type: 'warning', active: false },
  failed: { label: '失败', type: 'danger', active: false },
  cancelled: { label: '已取消', type: 'info', active: false },
  interrupted: { label: '已中断', type: 'warning', active: false },
} as const satisfies Record<SessionStatus, { label: string; type: string; active: boolean }>
export const stages = [
  { key: 'collect', label: '数据采集与共享输入' },
  { key: 'analyze', label: '并行 AI 分析' },
  { key: 'aggregate', label: '汇聚汇总' },
  { key: 'notify', label: '通知与投递回执' },
  { key: 'finish', label: '执行完成' },
] as const satisfies ReadonlyArray<{ key: WorkflowStage; label: string }>
export const availabilityLabels: Record<ArtifactAvailability, string> = {
  available: '可读取',
  pending: '尚未生成',
  not_saved: '未保存',
  expired: '已过期',
  missing: '文件缺失',
  corrupt: '文件损坏',
  write_failed: '写入失败',
}
export function formatTime(value: string) {
  return new Date(value).toLocaleString('zh-CN')
}
export function formatWorkflowName(value: string | null) {
  return value === null ? '名称未记录' : value || '未命名工作流'
}
