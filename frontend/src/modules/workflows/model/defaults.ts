import type { FanInConfig, WorkflowDefinition } from './types'
import { DEFAULT_DAILY_CRON } from './cronPresets'

export function createFanIn(): FanInConfig {
  return {
    order: [],
    separator: '\n\n',
    ai: null,
    model: null,
    prompt: '{input}',
    mark_incomplete: true,
  }
}

export function createWorkflow(): WorkflowDefinition {
  return {
    id: crypto.randomUUID(),
    name: '',
    sources: [],
    analyses: [],
    fan_in: null,
    channels: [],
    source_overrides: {},
    channel_overrides: {},
    input_separator: '\n\n',
    include_counts: true,
    collection_concurrency: 4,
    analysis_concurrency: 4,
    on_all_empty: 'stop',
    analysis_failure: 'continue',
    send_partial: true,
    schedule: { type: 'cron', expression: DEFAULT_DAILY_CRON, timezone: null },
    enabled: true,
    backup: {
      enabled: true,
      snapshot: true,
      collection: true,
      analysis: true,
      final: true,
      on_failure: 'stop',
      retention_days: null,
    },
  }
}

export function cloneWorkflow(value: WorkflowDefinition): WorkflowDefinition {
  return structuredClone(value)
}
