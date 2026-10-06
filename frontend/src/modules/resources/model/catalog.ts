import type { AIConfig } from './ai/types'
import type { ChannelConfig } from './channel/types'
import type { MCPServerConfig } from './mcp/types'
import type { SourceConfig } from './source/definition'
import { createSource } from './source/defaults'
import { createMCPServer } from './mcp/defaults'
import { createAIProvider } from './ai/defaults'
import { createChannel } from './channel/defaults'

export interface ResourceMap {
  sources: SourceConfig
  mcp_servers: MCPServerConfig
  ai: AIConfig
  channels: ChannelConfig
}
export type ResourceKind = keyof ResourceMap
export type EditableKind = ResourceKind
export type EditableResource = ResourceMap[ResourceKind]

export const resourceNames: Record<EditableKind, string> = {
  sources: '数据源',
  mcp_servers: 'MCP 服务',
  ai: '供应商渠道',
  channels: '通知渠道',
}
export const resourceKinds = [
  { key: 'sources', label: '数据源', icon: 'database' },
  { key: 'mcp_servers', label: 'MCP 服务', icon: 'database' },
  { key: 'ai', label: '供应商渠道', icon: 'bot' },
  { key: 'channels', label: '通知渠道', icon: 'mail' },
] as const

export function generatedResourceId(prefix?: string | null): string {
  const suffix = crypto.randomUUID()
  return prefix ? `${prefix}_${suffix}` : suffix
}

export function createResource(kind: EditableKind): EditableResource {
  const factories = {
    sources: createSource,
    mcp_servers: createMCPServer,
    ai: createAIProvider,
    channels: createChannel,
  }
  return factories[kind]()
}
