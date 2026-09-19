import type { WorkflowDefinition, FanInConfig } from '@/types'
// Defaults match WorkflowDefinition / FanInConfig in src/logagent/models.py.
export function createWorkflow(): WorkflowDefinition {
  return {
    id: '',
    name: '',
    sources: [],
    analyses: [],
    fan_in: null,
    channels: [],
    source_overrides: {},
    channel_overrides: {},
    input_separator: '\n\n',
    include_counts: false,
    collection_concurrency: 4,
    analysis_concurrency: 4,
    on_all_empty: 'stop',
    analysis_failure: 'continue',
    send_partial: true,
    interval_seconds: null,
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
