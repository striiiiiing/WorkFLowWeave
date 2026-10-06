import type { Credential } from '../credential'

export interface MCPServerConfig {
  id: string
  transport: 'stdio' | 'streamable_http' | 'sse'
  enabled: boolean
  health_check_enabled: boolean
  health_check_interval_minutes: number
  command: string | null
  args: string[]
  cwd: string | null
  url: string | null
  env: Record<string, Credential>
  headers: Record<string, Credential>
  timeout: number
}
