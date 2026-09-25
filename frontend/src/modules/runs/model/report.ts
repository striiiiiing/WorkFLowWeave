import type { ArtifactAvailability, ReportSection, WorkflowStage } from './types'
import type { JsonObject, JsonValue } from '@/shared/types'

export interface ReportItem {
  id: string
  status: string
  text: string
  error?: string
  count?: number
  sections?: ReportSection[]
  output?: string
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
function sections(value: JsonValue | undefined): ReportSection[] | undefined {
  if (value == null) return undefined
  return list(object(value).sections).map((raw): ReportSection => {
    const item = object(raw)
    const title = string(item.title)
    if (item.kind === 'text') return { kind: 'text', title, text: string(item.text) }
    if (item.kind === 'metrics')
      return {
        kind: 'metrics',
        title,
        items: list(item.items).map((raw) => {
          const metric = object(raw)
          if (typeof metric.value !== 'string' && typeof metric.value !== 'number')
            throw new Error('插件报告的指标格式无效。')
          return {
            label: string(metric.label),
            value: metric.value,
            unit: string(metric.unit ?? ''),
          }
        }),
      }
    if (item.kind === 'table') {
      const columns = list(item.columns).map(string)
      const rows = list(item.rows).map((row) =>
        list(row).map((cell) => {
          if (cell !== null && !['string', 'number', 'boolean'].includes(typeof cell))
            throw new Error('插件报告的表格单元格格式无效。')
          return cell as string | number | boolean | null
        }),
      )
      if (!columns.length || rows.some((row) => row.length !== columns.length))
        throw new Error('插件报告的表格列数不一致。')
      return { kind: 'table', title, columns, rows }
    }
    throw new Error('无法识别插件报告类型，请在高级模式查看原始数据。')
  })
}

export function parsePhase(stage: WorkflowStage, value: JsonValue): ParsedPhase {
  const body = object(value)
  const errors =
    body.errors == null ? [] : list(body.errors).map((item) => string(object(item).message))
  if (stage === 'aggregate')
    return {
      errors,
      items: Object.entries(object(body.outputs)).map(([id, text]) => ({
        id,
        text: string(text),
        status: 'success',
      })),
    }
  if (stage === 'finish')
    return { errors, items: [{ id: '运行结果', status: string(body.status), text: '' }] }
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
      text: stage === 'notify' ? '' : string(item.text),
      error: error(item.error),
    }
    if (stage === 'collect') {
      if (typeof item.count !== 'number') throw new Error('采集结果缺少数量。')
      result.count = item.count
      result.sections = sections(item.report)
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
    filtered_empty: '筛选后没有内容',
    missing: '来源不可用',
    failed: stage === 'notify' ? '投递失败' : '失败',
    timeout: '超时',
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
