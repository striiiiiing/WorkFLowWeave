import type { AgentEvent } from '@/api/agents'
export interface TranscriptRow {
  key: string
  role: 'user' | 'assistant' | 'tool' | 'summary' | 'status' | 'command'
  event: AgentEvent
  text: string
  status?: string
  group?: number
}
export function contentText(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value))
    return value
      .map((item) => (item?.type === 'text' && typeof item.text === 'string' ? item.text : ''))
      .join('')
  return ''
}
export function transcriptRows(events: AgentEvent[]): TranscriptRow[] {
  const rows: TranscriptRow[] = []
  const lookup = new Map<string, TranscriptRow>()
  let group = 0
  let toolFinished = false
  for (const event of events) {
    const data = event.data
    const base = `${event.session_id}:${event.id}`
    if (event.type === 'message.user')
      rows.push({ key: base, role: 'user', event, text: contentText(data.text) })
    else if (
      event.type === 'message.delta' ||
      (event.type === 'message.completed' && !data.incremental)
    ) {
      const content = contentText(data.content ?? data.text)
      if (!content) continue
      const key = `${event.session_id}:message:${data.message_id ?? event.turn_id}`
      let row = lookup.get(key)
      if (!row) {
        row = { key, role: 'assistant', event, text: '' }
        lookup.set(key, row)
        rows.push(row)
      }
      row.text += content
    } else if (event.type.startsWith('tool.')) {
      const key = `${event.session_id}:tool:${data.tool_key ?? data.tool_call_id}`
      let row = lookup.get(key)
      if (!row) {
        if (toolFinished) {
          group++
          toolFinished = false
        }
        row = { key, role: 'tool', event, text: '', group }
        lookup.set(key, row)
        rows.push(row)
      }
      row.event = event
      if (event.type === 'tool.completed' || event.type === 'tool.outcome_unknown')
        toolFinished = true
      row.status =
        event.type === 'tool.outcome_unknown'
          ? '结果未知，不自动重做'
          : event.type === 'tool.queued'
            ? '排队'
            : event.type === 'tool.started'
              ? '运行中'
              : String((data.result as Record<string, unknown> | undefined)?.status ?? '完成')
    } else if (event.type === 'context.compacted')
      rows.push({ key: base, role: 'summary', event, text: contentText(data.summary) })
    else if (event.type.startsWith('turn.')) {
      if (event.type !== 'turn.started')
        rows.push({ key: base, role: 'status', event, text: event.type.slice(5) })
    } else if (event.type.startsWith('command.')) {
      const key = `${event.session_id}:command:${data.request_id ?? data.command_event_id ?? event.id}`
      let row = lookup.get(key)
      if (!row) {
        row = { key, role: 'command', event, text: '' }
        lookup.set(key, row)
        rows.push(row)
      }
      row.event = event
      row.text =
        event.type === 'command.queued'
          ? `${data.command} 已排队，将在工具组完成后的模型边界处理`
          : `${data.command} ${event.type === 'command.failed' ? '处理失败，原始历史保留' : event.type === 'command.cancelled' ? '已取消' : data.compacted === false ? '没有可压缩的早期消息' : '已处理'}`
    }
  }
  return rows
}
