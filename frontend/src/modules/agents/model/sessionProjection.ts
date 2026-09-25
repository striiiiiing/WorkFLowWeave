import type { AgentEvent, AgentSession, ContextBudget } from './types'
import { terminalTurnEvents } from './events'

export function projectAgentSession(session: AgentSession, event: AgentEvent): AgentSession {
  if (event.session_id !== session.session_id) return session
  if (event.type === 'turn.started') {
    if (session.status === 'running' && session.turn_id !== event.turn_id) return session
    return { ...session, status: 'running', turn_id: event.turn_id }
  }
  if (event.turn_id !== session.turn_id) return session
  if (event.type === 'context.budget')
    return { ...session, context_budget: event.data as unknown as ContextBudget }
  if (event.type === 'turn.resources')
    return {
      ...session,
      active_resources: {
        model: event.data.model as string | null,
        tools_generation: event.data.tools_generation as number | null,
      },
    }
  if (!terminalTurnEvents.has(event.type)) return session
  const error = event.data.error
  const continuationError =
    error &&
    typeof error === 'object' &&
    !Array.isArray(error) &&
    'code' in error &&
    'message' in error &&
    typeof error.code === 'string' &&
    typeof error.message === 'string'
      ? { code: error.code, message: error.message }
      : undefined
  return {
    ...session,
    status: event.type.slice(5),
    ...(event.data.checkpoint_id ? { last_checkpoint_at: event.at } : {}),
    ...(continuationError &&
    ['checkpoint_missing', 'checkpoint_corrupt'].includes(continuationError.code)
      ? { continuable: false, continuation_error: continuationError }
      : {}),
  }
}
