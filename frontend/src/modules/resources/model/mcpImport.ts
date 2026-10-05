import type { JsonObject } from '@/shared/types'
import { createResource } from './resources'
import type { Credential, MCPServerConfig } from './types'

export interface McpConfig {
  servers: Record<string, Record<string, unknown>>
}

function record(value: unknown, message: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(message)
  return value as Record<string, unknown>
}

function text(value: unknown, fallback: string | null = null): string | null {
  return value === undefined || value === null ? fallback : typeof value === 'string' ? value : null
}

export function parseMcpConfig(input: string): McpConfig {
  let parsed: unknown
  try {
    parsed = JSON.parse(input)
  } catch {
    throw new Error('JSON 格式不正确，请检查双引号、逗号和括号是否完整。')
  }
  const root = record(parsed, '配置必须是 JSON 对象。')
  const serversValue = root.servers ?? root.mcpServers
  const servers = record(serversValue, '配置必须包含 servers 对象。')
  const normalized: McpConfig['servers'] = {}
  for (const [name, value] of Object.entries(servers)) {
    if (!/^[A-Za-z0-9_-]{1,80}$/.test(name)) {
      throw new Error(`MCP 服务名称无效：${name}`)
    }
    normalized[name] = record(value, `MCP 服务 ${name} 必须是对象。`)
  }
  return { servers: normalized }
}

export function serverToResource(
  name: string,
  value: Record<string, unknown>,
  health?: Pick<MCPServerConfig, 'health_check_enabled' | 'health_check_interval_minutes'>,
): MCPServerConfig {
  const type = value.type === undefined ? 'stdio' : value.type
  const transport = type === 'http' ? 'streamable_http' : type
  if (!['stdio', 'streamable_http', 'sse'].includes(String(transport))) {
    throw new Error(`MCP 服务 ${name} 的 type 不受支持。`)
  }
  const args = value.args === undefined ? [] : value.args
  if (!Array.isArray(args) || args.some((item) => typeof item !== 'string')) {
    throw new Error(`MCP 服务 ${name} 的 args 必须是字符串数组。`)
  }
  const base = createResource('mcp_servers') as MCPServerConfig
  return {
    ...base,
    id: name,
    transport: transport as MCPServerConfig['transport'],
    enabled: value.enabled !== false,
    health_check_enabled: health?.health_check_enabled ?? false,
    health_check_interval_minutes: health?.health_check_interval_minutes ?? 30,
    command: text(value.command),
    args: [...args],
    cwd: text(value.cwd),
    url: text(value.url),
    env: (value.env ?? {}) as Record<string, Credential>,
    headers: (value.headers ?? {}) as Record<string, Credential>,
    timeout: typeof value.timeout === 'number' ? value.timeout : 60,
  }
}

export function resourceToMcpConfig(value: MCPServerConfig): McpConfig {
  const server: Record<string, unknown> = {
    type: value.transport === 'streamable_http' ? 'http' : value.transport,
    enabled: value.enabled,
    timeout: value.timeout,
  }
  if (value.transport === 'stdio') {
    server.command = value.command
    server.args = [...value.args]
    if (value.cwd) server.cwd = value.cwd
    if (Object.keys(value.env).length) server.env = value.env
  } else {
    server.url = value.url
    if (Object.keys(value.headers).length) server.headers = value.headers
  }
  return { servers: { [value.id]: server } }
}

export function mcpExample(): McpConfig {
  return { servers: {} }
}

export type McpJson = McpConfig & JsonObject
