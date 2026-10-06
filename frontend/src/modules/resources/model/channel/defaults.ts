import type { ChannelConfig } from './types'

export function createChannel(): ChannelConfig {
  return {
    id: crypto.randomUUID(),
    channel: '',
    options: {},
    timeout: 30,
    enabled: true,
    agent_enabled: false,
  }
}
