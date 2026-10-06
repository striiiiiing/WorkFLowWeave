import type { MCPServerConfig } from './types'

export function createMCPServer(): MCPServerConfig {
  return {
    id: crypto.randomUUID(),
    transport: 'stdio',
    enabled: true,
    health_check_enabled: false,
    health_check_interval_minutes: 30,
    command: '',
    args: [],
    cwd: null,
    url: null,
    env: {},
    headers: {},
    timeout: 60,
  }
}
