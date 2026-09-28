import type { SessionRecord, SessionStatus, WorkflowProgress } from './types'

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

function progressVersion(item: WorkflowProgress) {
  return item.version ?? -1
}

/** Merge by the server's business identity and version, preserving snapshot order. */
export function mergeProgress(
  current: readonly WorkflowProgress[] = [],
  updates: readonly WorkflowProgress[] = [],
) {
  const merged = current.map((item) => ({ ...item }))
  const indexes = new Map(merged.map((item, index) => [progressIdentity(item), index]))
  for (const update of updates) {
    const key = progressIdentity(update)
    const index = indexes.get(key)
    if (index === undefined) {
      indexes.set(key, merged.length)
      merged.push({ ...update })
      continue
    }
    const previous = merged[index]
    if (progressVersion(update) >= progressVersion(previous))
      merged[index] = { ...previous, ...update, label: update.label ?? previous.label }
  }
  return merged
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

/** Apply one committed event without allowing a stale event to regress the session. */
export function applyProgress(session: SessionRecord, event: WorkflowProgress): SessionRecord {
  const next: SessionRecord = {
    ...session,
    version: Math.max(session.version, event.version ?? session.version),
    progress:
      event.event === 'lifecycle' ? session.progress : mergeProgress(session.progress, [event]),
  }
  if ((event.version ?? -1) >= session.version && event.stage !== null) next.stage = event.stage
  if (
    event.event === 'lifecycle' &&
    isSessionStatus(event.status) &&
    (event.version ?? -1) >= session.version
  ) {
    next.status = event.status
    next.stage = event.stage
    next.error = event.error
  }
  return next
}

export function mergeSessionSnapshot(
  current: SessionRecord | undefined,
  snapshot: SessionRecord,
): SessionRecord {
  const normalized = {
    ...snapshot,
    execution_epoch: snapshot.execution_epoch ?? null,
    progress: snapshot.progress ?? [],
  }
  if (!current || current.execution_epoch !== snapshot.execution_epoch) return normalized
  const newer = snapshot.version >= current.version ? normalized : current
  return {
    ...newer,
    progress: mergeProgress(normalized.progress, current.progress ?? []),
  }
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
