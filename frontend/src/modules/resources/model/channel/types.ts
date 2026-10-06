import type { JsonObject } from '@/shared/types'

export interface ChannelConfig {
  id: string
  channel: string
  options: JsonObject
  timeout: number
  enabled: boolean
  agent_enabled?: boolean
}

export interface ChannelOverride {
  options: JsonObject
}
