import type { AIConfig, ChannelConfig, JsonObject, SourceConfig } from '@/types'
export type EditableKind = 'sources' | 'ai' | 'channels'
export type EditableResource = SourceConfig | AIConfig | ChannelConfig
export const resourceNames: Record<EditableKind, string> = {
  sources: '数据源',
  ai: '供应商渠道',
  channels: '通知渠道',
}
export const resourceKinds = [
  { key: 'sources', label: '数据源', icon: 'database' },
  { key: 'ai', label: '供应商渠道', icon: 'bot' },
  { key: 'channels', label: '通知渠道', icon: 'mail' },
] as const

export function generatedResourceId(prefix?: string | null): string {
  const suffix = crypto.randomUUID()
  return prefix ? `${prefix}_${suffix}` : suffix
}

export function credentialPropertyNames(schema: JsonObject | undefined): string[] {
  const properties = (schema?.properties ?? {}) as Record<string, JsonObject>
  return Object.keys(properties).filter(
    (name) => properties[name]['x-logagent-credential'] === true,
  )
}

// Initial values follow the backend models, including the AI execution budget.
export function createResource(kind: EditableKind): EditableResource {
  const factories = {
    sources: (): SourceConfig => ({
      id: crypto.randomUUID(),
      collector: '',
      display_name: '',
      description: '',
      enabled: true,
      options: {},
      setters: {},
      template: null,
      timeout: 60,
      on_error: 'notice',
      on_missing: 'notice',
      on_empty: 'notice',
      on_filtered_empty: 'notice',
    }),
    ai: (): AIConfig => ({
      id: crypto.randomUUID(),
      provider: 'openai_compatible_api',
      base_url: null,
      api_key: null,
      system_prompt: '',
      models: {},
      timeout: 600,
      retries: 5,
    }),
    channels: (): ChannelConfig => ({
      id: crypto.randomUUID(),
      channel: '',
      options: {},
      timeout: 30,
      enabled: true,
      agent_enabled: false,
    }),
  }
  return factories[kind]()
}

export function sourceName(source: SourceConfig): string {
  return source.display_name || source.id
}

// Transitional export; source usage is owned by workflows/model and removed by P7.
export { sourceUsage } from '@/modules/workflows/public'
