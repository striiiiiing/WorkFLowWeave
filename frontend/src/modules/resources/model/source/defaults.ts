import type { SourceConfig } from './definition'

export function createSource(): SourceConfig {
  return {
    id: crypto.randomUUID(),
    call: { kind: 'mcp', server: '', tool: '', arguments: {} },
    display_name: '',
    description: '',
    enabled: true,
    limits: { item_tokens: null, field_tokens: null },
    timeout: 60,
    on_error: 'notice',
    on_missing: 'notice',
    on_empty: 'notice',
  }
}
