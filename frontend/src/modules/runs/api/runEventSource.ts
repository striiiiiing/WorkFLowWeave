import { createEventSource, type EventConnection } from '@/shared/api/eventSource'
import type { SessionRecord } from '../model/types'

export interface RunEventHandlers {
  snapshot: (record: SessionRecord) => void
  state: (state: 'connected' | 'reconnecting') => void
  error: (cause: unknown) => void
}
export type RunEventConnection = EventConnection
export type RunEventTransport = ((sessionId: string, handlers: RunEventHandlers) => () => void) & {
  available?: boolean
}

const statuses = new Set(['created', 'running', 'completed', 'partial', 'failed', 'cancelled', 'interrupted'])
const stages = new Set(['collect', 'analyze', 'aggregate', 'notify', 'finish'])
const availability = new Set(['available', 'pending', 'not_saved', 'expired', 'missing', 'corrupt', 'write_failed'])

export function parseRunSnapshot(value: unknown): SessionRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new Error('Workflow 快照格式无效')
  const record = value as Record<string, unknown>
  if (
    typeof record.session_id !== 'string' || !record.session_id ||
    typeof record.workflow_id !== 'string' ||
    !Number.isSafeInteger(record.version) || Number(record.version) < 0 ||
    !statuses.has(String(record.status)) ||
    (record.stage !== null && !stages.has(String(record.stage))) ||
    (record.execution_epoch !== null && typeof record.execution_epoch !== 'string') ||
    !Array.isArray(record.artifacts) || !Array.isArray(record.progress)
  ) throw new Error('Workflow 快照字段不符合接口契约')
  for (const artifact of record.artifacts) {
    if (!artifact || typeof artifact !== 'object' ||
      !stages.has(String(artifact.stage)) ||
      !availability.has(String(artifact.availability)) ||
      (artifact.content_version !== null &&
        (!Number.isSafeInteger(artifact.content_version) || artifact.content_version < 0)))
      throw new Error('Workflow 正文元数据无效')
  }
  for (const item of record.progress) {
    if (!item || typeof item !== 'object' ||
      typeof item.session_id !== 'string' ||
      !Number.isSafeInteger(item.order) || item.order < 0 ||
      !['item', 'aggregate', 'delivery', 'lifecycle'].includes(item.event))
      throw new Error('Workflow 逐项进度无效')
  }
  return value as SessionRecord
}

export function createRunEventSource(
  sourceFactory: (url: string) => RunEventConnection = (url) => new EventSource(url),
  clock: Pick<typeof globalThis, 'setTimeout' | 'clearTimeout'> = globalThis,
): RunEventTransport {
  const transport = ((sessionId, handlers) => {
    const connection = createEventSource(sourceFactory, clock)
    connection.open({
      url: () => `/api/sessions/${encodeURIComponent(sessionId)}/events`,
      event: 'snapshot',
      parse: (value) => {
        const record = parseRunSnapshot(value)
        if (record.session_id !== sessionId) throw new Error('Workflow 快照会话不匹配')
        return record
      },
      data: handlers.snapshot,
      state: handlers.state,
      error: handlers.error,
    })
    return connection.close
  }) as RunEventTransport
  transport.available = typeof globalThis.EventSource === 'function'
  return transport
}
