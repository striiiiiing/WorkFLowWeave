import { isErrorInfo } from '@/shared/api/errors'
import { isTerminalStatus } from '../model/progress'
import type { WorkflowProgress } from '../model/types'

export interface RunEventHandlers {
  ready: () => void
  progress: (event: WorkflowProgress) => void
  disconnected: (message: string) => void
}
export type RunEventConnection = Pick<EventSource, 'addEventListener' | 'close' | 'onerror'>
export type RunEventTransport = ((sessionId: string, handlers: RunEventHandlers) => () => void) & {
  /** False when the runtime has no EventSource implementation. */
  available?: boolean
}

const stages = new Set(['collect', 'analyze', 'aggregate', 'notify', 'finish'])
const events = new Set(['item', 'aggregate', 'delivery', 'lifecycle'])
const availability = new Set([
  'available',
  'pending',
  'not_saved',
  'expired',
  'missing',
  'corrupt',
  'write_failed',
])

function nullableString(value: unknown) {
  return value === null || typeof value === 'string'
}

export function parseRunProgress(value: unknown): WorkflowProgress {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new Error('Workflow 进度格式无效')
  const item = value as Record<string, unknown>
  if (
    typeof item.session_id !== 'string' ||
    !item.session_id ||
    !nullableString(item.execution_epoch) ||
    (item.stage !== null && !stages.has(String(item.stage))) ||
    !events.has(String(item.event)) ||
    typeof item.status !== 'string' ||
    !item.status ||
    !['item_id', 'output_id', 'channel_id', 'label', 'result_ref'].every((key) =>
      nullableString(item[key]),
    ) ||
    (item.version !== null && (!Number.isSafeInteger(item.version) || Number(item.version) < 0)) ||
    !availability.has(String(item.availability)) ||
    (item.error !== null && !isErrorInfo(item.error)) ||
    !item.summary ||
    typeof item.summary !== 'object' ||
    Array.isArray(item.summary)
  )
    throw new Error('Workflow 进度字段不符合接口契约')
  if (
    item.event === 'item' &&
    (!item.item_id || !['collect', 'analyze'].includes(String(item.stage)))
  )
    throw new Error('Workflow 单项进度缺少业务身份')
  if (item.event === 'delivery' && (!item.output_id || !item.channel_id || item.stage !== 'notify'))
    throw new Error('Workflow 投递进度缺少业务身份')
  if (item.event === 'aggregate' && item.stage !== 'aggregate')
    throw new Error('Workflow 汇总进度阶段无效')
  return item as unknown as WorkflowProgress
}

/** EventSource owns reconnect timing; every ready signal establishes a fresh query boundary. */
export function createRunEventSource(
  sourceFactory: (url: string) => RunEventConnection = (url) => new EventSource(url),
): RunEventTransport {
  const transport = ((sessionId, handlers) => {
    const source = sourceFactory(`/api/sessions/${encodeURIComponent(sessionId)}/events`)
    let closed = false
    const close = () => {
      closed = true
      source.close()
    }
    const read = (message: Event, action: (value: unknown) => void) => {
      if (closed) return
      try {
        action(JSON.parse((message as MessageEvent<string>).data))
      } catch (cause) {
        close()
        handlers.disconnected(cause instanceof Error ? cause.message : String(cause))
      }
    }
    source.addEventListener('ready', (message) =>
      read(message, (value) => {
        if (
          !value ||
          typeof value !== 'object' ||
          !('session_id' in value) ||
          value.session_id !== sessionId
        )
          throw new Error('Workflow 订阅会话不匹配')
        handlers.ready()
      }),
    )
    source.addEventListener('progress', (message) =>
      read(message, (value) => {
        const event = parseRunProgress(value)
        if (event.session_id !== sessionId) throw new Error('Workflow 进度会话不匹配')
        if (event.event === 'lifecycle' && isTerminalStatus(event.status)) close()
        handlers.progress(event)
      }),
    )
    source.addEventListener('resync', () => {
      if (closed) return
      close()
      handlers.disconnected('进度订阅已中断，请重新同步')
    })
    source.onerror = () => {
      if (!closed) handlers.disconnected('进度连接中断，正在重新连接；当前显示最后已知结果')
    }
    return close
  }) as RunEventTransport
  transport.available = typeof globalThis.EventSource === 'function'
  return transport
}
