import type { SourcePolicy, SourceOverride } from '@/modules/resources/model/public'

export interface InputProcessing {
  format: 'none' | 'ison' | 'toon' | 'zon' | 'md' | 'csv'
  total_tokens: number | null
  item_tokens: number | null
  field_tokens: number | null
}

export interface CollectionConfig {
  sources: string[]
  source_overrides: Record<string, SourceOverride>
  input_separator: string
  input_processing: InputProcessing
  collection_concurrency: number
  on_all_empty: SourcePolicy
}

export function createCollectionDefaults(): CollectionConfig {
  return {
    sources: [],
    source_overrides: {},
    input_separator: '\n\n',
    input_processing: { format: 'none', total_tokens: null, item_tokens: null, field_tokens: null },
    collection_concurrency: 4,
    on_all_empty: 'stop',
  }
}
