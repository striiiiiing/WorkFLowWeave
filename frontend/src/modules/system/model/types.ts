import type { ErrorInfo, JsonObject } from '@/shared/types'

export interface CapabilityDescription {
  kind: 'channel' | 'tool'
  name: string
  id_prefix?: string | null
  description: string
  plugin: string
  capabilities: string[]
  options_schema: JsonObject
  input_schema?: JsonObject | null
  execution?: 'read' | 'exclusive'
}
export interface DiscoveryReport {
  registered: CapabilityDescription[]
  errors: ErrorInfo[]
}
export interface ComponentHealth {
  component: string
  status: 'available' | 'degraded' | 'unavailable' | 'unknown'
  required: boolean
  error: ErrorInfo | null
  checked_at: string | null
}
export interface HealthReport {
  status: 'ready' | 'degraded' | 'unavailable'
  accepting_runs: boolean
  checked_at: string
  components: ComponentHealth[]
}
