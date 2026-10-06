import type { SourceCall } from './call'
import type { SourceParameters } from './parameters'
import type { SourceSetters } from './setters'

export type SourcePolicy = 'stop' | 'notice' | 'skip'
export interface SourceLimits {
  item_tokens: number | null
  field_tokens: number | null
}
export interface SourceConfig extends SourceSetters {
  id: string
  display_name?: string | null
  description?: string
  call: SourceCall | null
  options?: SourceParameters
  enabled: boolean
  limits: SourceLimits
  timeout: number
  on_error: SourcePolicy
  on_missing: SourcePolicy
  on_empty: SourcePolicy
}

export type SourceBasicChanges = Partial<
  Pick<SourceConfig, 'display_name' | 'description' | 'enabled'>
>
export type SourceAdvancedChanges = Partial<
  Pick<SourceConfig, 'timeout' | 'on_error' | 'on_missing' | 'on_empty' | 'limits'>
>

export function sourceName(source: SourceConfig): string {
  return source.display_name || source.id
}
