import { agentsApi, type AgentEvent } from '@/api/agents'
import { createAgentEventSource } from '@/modules/agents/api/agentEventSource'
import { useAgentSession } from '@/modules/agents/composables/useAgentSession'

export { mergeAgentEvents } from '@/modules/agents/model/events'

// P6 can replace this legacy import after the Agent page moves into the module.
export function useAgentStream(onEvent: (event: AgentEvent) => void) {
  return useAgentSession(agentsApi, createAgentEventSource(), onEvent)
}
