import type { AgentEvent } from './types'

export const terminalTurnEvents = new Set([
  'turn.completed',
  'turn.failed',
  'turn.cancelled',
  'turn.interrupted',
])

const knownEvents = new Set([
  'message.user',
  'message.delta',
  'message.completed',
  'tool.queued',
  'tool.started',
  'tool.completed',
  'tool.outcome_unknown',
  'turn.started',
  'turn.resources',
  ...terminalTurnEvents,
  'context.budget',
  'context.compacted',
  'command.queued',
  'command.completed',
  'command.failed',
  'command.cancelled',
  'request.accepted',
])

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function content(value: unknown): boolean {
  return (
    typeof value === 'string' ||
    (Array.isArray(value) &&
      value.every(
        (part) => record(part) && (part.type !== 'text' || typeof part.text === 'string'),
      ))
  )
}

function validPayload(type: string, data: Record<string, unknown>, turnId: string | null): boolean {
  if (type === 'message.user') return typeof data.text === 'string'
  if (type === 'message.delta') return content(data.content) || data.tool_calls !== undefined
  if (type === 'message.completed')
    return typeof data.incremental === 'boolean' && (data.incremental || content(data.text))
  if (type === 'context.compacted') return typeof data.summary === 'string'
  if (type === 'context.budget')
    return (
      ['messages', 'system', 'tools', 'output', 'total', 'window', 'remaining'].every(
        (field) => typeof data[field] === 'number' && Number.isFinite(data[field]),
      ) &&
      (data.trigger === undefined || typeof data.trigger === 'number') &&
      typeof data.estimated === 'boolean' &&
      typeof data.token_counter === 'string'
    )
  if (type === 'turn.resources')
    return (
      typeof turnId === 'string' &&
      !!turnId &&
      (data.model === null || typeof data.model === 'string') &&
      (data.tools_generation === null || typeof data.tools_generation === 'number')
    )
  if (type.startsWith('turn.')) return typeof turnId === 'string' && !!turnId
  if (type.startsWith('tool.')) return typeof data.tool_key === 'string'
  if (type.startsWith('command.')) return typeof data.command === 'string'
  return true
}

export function parseAgentEvent(value: unknown): AgentEvent {
  if (
    !record(value) ||
    !Number.isSafeInteger(value.id) ||
    (value.id as number) < 1 ||
    typeof value.session_id !== 'string' ||
    !value.session_id ||
    (value.turn_id !== null && typeof value.turn_id !== 'string') ||
    typeof value.type !== 'string' ||
    !value.type ||
    typeof value.at !== 'string' ||
    !record(value.data)
  )
    throw new Error('Agent 事件信封无效')
  if (knownEvents.has(value.type) && !validPayload(value.type, value.data, value.turn_id))
    throw new Error(`Agent 事件 ${value.type} 的内容无效`)
  return value as unknown as AgentEvent
}

export function mergeAgentEvents(current: AgentEvent[], incoming: AgentEvent[]): AgentEvent[] {
  const seen = new Set(current.map((event) => `${event.session_id}:${event.id}`))
  return [
    ...current,
    ...incoming.filter((event) => {
      const key = `${event.session_id}:${event.id}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    }),
  ]
}
