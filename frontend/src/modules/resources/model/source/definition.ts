import type { SourceCall } from './call'

export type SourcePolicy = 'stop' | 'notice' | 'skip'
export interface SourceLimits {
  item_tokens: number | null
  field_tokens: number | null
}
export interface SourceConfig {
  id: string
  display_name?: string | null
  description?: string
  call: SourceCall
  enabled: boolean
  limits: SourceLimits
  timeout: number
  on_error: SourcePolicy
  on_empty: SourcePolicy
}

export type SourceBasicChanges = Partial<
  Pick<SourceConfig, 'display_name' | 'description' | 'enabled'>
>
export type SourceAdvancedChanges = Partial<
  Pick<SourceConfig, 'timeout' | 'on_error' | 'on_empty' | 'limits'>
>

export function sourceName(source: SourceConfig): string {
  return source.display_name || source.id
}
