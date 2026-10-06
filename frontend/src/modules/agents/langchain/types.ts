import type { BaseMessage } from '@langchain/core/messages'

export interface AgentStreamState extends Record<string, unknown> {
  messages: BaseMessage[]
}

export type AgentStreamConnectionState = 'loading' | 'connected' | 'reconnecting' | 'closed'
