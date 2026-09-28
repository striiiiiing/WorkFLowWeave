import type { SessionStatus, WorkflowProgress } from './types'

type TerminalSessionStatus = Exclude<SessionStatus, 'created' | 'running'>

const terminalStatuses = new Set<TerminalSessionStatus>([
  'completed',
  'partial',
  'failed',
  'cancelled',
  'interrupted',
])

export const progressStages = ['collect', 'analyze', 'aggregate', 'notify'] as const

export function progressIdentity(
  item: Pick<WorkflowProgress, 'stage' | 'event' | 'item_id' | 'output_id' | 'channel_id'>,
) {
  return [
    item.stage ?? '',
    item.event,
    item.item_id ?? '',
    item.output_id ?? '',
    item.channel_id ?? '',
  ].join(':')
}

function isSessionStatus(value: string): value is SessionStatus {
  return [
    'created',
    'running',
    'completed',
    'partial',
    'failed',
    'cancelled',
    'interrupted',
  ].includes(value)
}

export function isTerminalStatus(value: string): value is TerminalSessionStatus {
  return isSessionStatus(value) && terminalStatuses.has(value as TerminalSessionStatus)
}

export function progressItemLabel(item: WorkflowProgress) {
  if (item.label) return item.label
  if (item.event === 'delivery')
    return [item.output_id, item.channel_id].filter(Boolean).join(' · ')
  return item.item_id ?? item.output_id ?? '未命名项目'
}

export function progressStatusLabel(item: WorkflowProgress) {
  if (item.event === 'delivery') {
    if (item.status === 'success') return '已发送'
    if (item.status === 'delivery_uncertain') return '投递结果不确定'
    if (item.status === 'skipped') return '未发送'
    if (item.status === 'failed') return '投递失败'
  }
  if (item.event === 'aggregate') {
    if (item.status === 'success') return '报告已生成'
    if (item.status === 'failed') return '汇总失败'
  }
  const labels: Record<string, string> = {
    pending: '等待中',
    running: '执行中',
    success: '已完成',
    empty: '没有内容',
    filtered_empty: '筛选后没有内容',
    missing: '来源不可用',
    failed: '失败',
    timeout: '超时',
    cancelled: '已取消',
    skipped: '已跳过',
  }
  return labels[item.status] ?? `未知状态：${item.status}`
}

export function progressTagType(item: WorkflowProgress) {
  if (['failed', 'timeout', 'delivery_uncertain', 'missing'].includes(item.status)) return 'danger'
  if (['pending', 'running'].includes(item.status)) return 'info'
  if (['empty', 'filtered_empty', 'skipped', 'cancelled'].includes(item.status)) return 'warning'
  return 'success'
}
