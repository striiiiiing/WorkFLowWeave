import type { WorkflowStage } from '../shared/types'
import type { JsonObject, JsonValue } from '@/shared/types'

export interface ReportItem {
  id: string
  status: string
  text: string
  agentSessionId?: string
  error?: string
  output?: string
  processedText?: string
  processingStatus?: string
  truncated?: boolean
  omitted?: boolean
  exitCode?: number
}
export interface ParsedPhase {
  items: ReportItem[]
  errors: string[]
}

function object(value: JsonValue | undefined): JsonObject {
  if (value === null || typeof value !== 'object' || Array.isArray(value))
    throw new Error('结果结构不符合约定，请在高级模式查看原始数据。')
  return value
}
function string(value: JsonValue | undefined): string {
  if (typeof value !== 'string') throw new Error('结果缺少文字字段，请在高级模式查看原始数据。')
  return value
}
function list(value: JsonValue | undefined): JsonValue[] {
  if (!Array.isArray(value)) throw new Error('结果缺少列表字段，请在高级模式查看原始数据。')
  return value
}
function error(value: JsonValue | undefined): string | undefined {
  return value == null ? undefined : string(object(value).message)
}
function collectionText(raw: JsonValue | undefined): string {
  if (raw == null) return ''
  const value = object(raw)
  if (typeof value.stdout === 'string') {
    return [
      value.stdout,
      typeof value.stderr === 'string' && value.stderr ? `stderr:\n${value.stderr}` : '',
    ]
      .filter(Boolean)
      .join('\n\n')
  }
  const blocks = Array.isArray(value.content)
    ? value.content.map((block) => {
        const content = object(block)
        return content.type === 'text' ? string(content.text) : JSON.stringify(content, null, 2)
      })
    : []
  if (value.structuredContent != null) blocks.push(JSON.stringify(value.structuredContent, null, 2))
  return blocks.join('\n\n')
}

export function parsePhase(stage: WorkflowStage, value: JsonValue): ParsedPhase {
  const body = object(value)
  const errors =
    body.errors == null ? [] : list(body.errors).map((item) => string(object(item).message))
  if (stage === 'aggregate') {
    const items: ReportItem[] = Object.entries(object(body.outputs)).map(([id, text]) => ({
      id,
      text: string(text),
      status: 'success',
    }))
    if (body.aggregate != null) {
      const aggregate = object(body.aggregate)
      const final = items.find((item) => item.id === 'final')
      const result: ReportItem = {
        id: 'final',
        text: final?.text ?? (aggregate.text == null ? '' : string(aggregate.text)),
        status: aggregate.status == null ? 'success' : string(aggregate.status),
        error: error(aggregate.error),
        ...(typeof aggregate.agent_session_id === 'string'
          ? { agentSessionId: aggregate.agent_session_id }
          : {}),
      }
      if (final) items[items.indexOf(final)] = result
      else items.push(result)
    }
    return { errors, items }
  }
  if (stage === 'finish')
    return { errors, items: [{ id: '运行结果', status: string(body.status), text: '' }] }
  const inputViews =
    stage === 'collect' && body.input_views != null
      ? new Map(
          list(body.input_views).map((raw) => {
            const view = object(raw)
            return [string(view.source_id), view] as const
          }),
        )
      : undefined
  const entries = list(
    body[stage === 'collect' ? 'collection' : stage === 'analyze' ? 'analyses' : 'deliveries'],
  )
  const items = entries.map((raw): ReportItem => {
    const item = object(raw)
    const result: ReportItem = {
      id: string(
        item[stage === 'collect' ? 'source_id' : stage === 'analyze' ? 'task_id' : 'channel_id'],
      ),
      status: string(item.status),
      text:
        stage === 'notify'
          ? ''
          : stage === 'collect'
            ? collectionText(item.raw)
            : string(item.text),
      error: error(item.error),
      ...(typeof item.agent_session_id === 'string'
        ? { agentSessionId: item.agent_session_id }
        : {}),
    }
    if (stage === 'collect') {
      const view = inputViews?.get(result.id)
      if (view) {
        result.processingStatus = string(view.status)
        result.processedText = typeof view.text === 'string' ? view.text : ''
        result.truncated = view.truncated === true
        result.omitted = view.omitted === true
        result.error ??= error(view.error)
      }
      const raw = item.raw == null ? undefined : object(item.raw)
      if (typeof raw?.exit_code === 'number') result.exitCode = raw.exit_code
    }
    if (stage === 'notify') {
      result.output = string(item.output_id)
      if (item.error && object(item.error).code === 'delivery_uncertain')
        result.status = 'uncertain'
    }
    return result
  })
  return { items, errors }
}

export function resultStatus(status: string, stage: WorkflowStage): string {
  const labels: Record<string, string> = {
    success: stage === 'notify' ? '已送达' : '已完成',
    empty: '没有采集到内容',
    failed: stage === 'notify' ? '投递失败' : '失败',
    timeout: '超时',
    unknown: '结果不确定',
    cancelled: '已取消',
    skipped: '渠道已停用，未发送',
    uncertain: '投递结果不确定',
    completed: '已完成',
    partial: '部分完成',
    running: '运行中',
    interrupted: '已中断',
    created: '等待执行',
  }
  return labels[status] ?? `未知状态：${status}`
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
