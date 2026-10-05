import type { AnalysisTask, FanInConfig, WorkflowDefinition } from './types'
import { DEFAULT_DAILY_CRON } from './cronPresets'

export function defaultFanInModelSource(analyses: readonly AnalysisTask[]): string | null {
  return analyses.length ? '$first' : null
}

export function createFanIn(analyses: readonly AnalysisTask[] = []): FanInConfig {
  return {
    order: [],
    separator: '\n\n',
    ai: null,
    model: null,
    system_prompt: null,
    input_prompt: null,
    user_prompt: '',
    agent_mode: false,
    agent_tools: null,
    reuse_from: defaultFanInModelSource(analyses),
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
    system_prompt: '',
    input_prompt: '{input}',
    channels: [],
    source_overrides: {},
    channel_overrides: {},
    input_separator: '\n\n',
    input_processing: { format: 'none', total_tokens: null, item_tokens: null, field_tokens: null },
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
      checkpoint_retention_days: null,
      collection_retention_days: null,
      analysis_retention_days: null,
      final_retention_days: null,
    },
  }
}

export function cloneWorkflow(value: WorkflowDefinition): WorkflowDefinition {
  return structuredClone(value)
}
