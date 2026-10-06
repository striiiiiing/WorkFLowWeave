import type { JsonObject } from '@/shared/types'

// Retained for existing Collector data; new calls use MCP or CLI.
export interface SourceSetters {
  collector?: string | null
  setters?: JsonObject
  template?: string | null
}
