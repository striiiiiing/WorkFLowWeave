import type { AIConfig, ChannelConfig, SetterTemplate, SourceConfig } from '@/types'
export type EditableKind = 'sources' | 'setters' | 'ai' | 'channels'
export type EditableResource = SourceConfig | SetterTemplate | AIConfig | ChannelConfig
export const resourceNames: Record<EditableKind, string> = {
  sources: '数据源',
  setters: '处理模板',
  ai: '供应商渠道',
  channels: '通知渠道',
}
export const resourceKinds = [
  { key: 'sources', label: '数据源', icon: 'database' },
  { key: 'setters', label: '处理模板', icon: 'settings' },
  { key: 'ai', label: 'AI 配置', icon: 'bot' },
  { key: 'channels', label: '通知渠道', icon: 'mail' },
] as const
// Initial values follow the backend models, including the AI execution budget.
export function createResource(kind: EditableKind): EditableResource {
  const factories = {
    sources: (): SourceConfig => ({
      id: crypto.randomUUID(),
      collector: '',
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
    setters: (): SetterTemplate => ({ id: crypto.randomUUID(), collector: '', setters: {} }),
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
    }),
  }
  return factories[kind]()
}
