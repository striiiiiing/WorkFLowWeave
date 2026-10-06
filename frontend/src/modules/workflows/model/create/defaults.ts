import type { WorkflowDefinition } from './definition'
import { DEFAULT_DAILY_CRON } from './cronPresets'
import { createCollectionDefaults } from './stages/collection'
import { createAnalysisDefaults } from './stages/analysis'
import { createNotificationDefaults } from './stages/notification'
import { createBackupPolicy } from './backup'

export function createWorkflow(): WorkflowDefinition {
  const collection = createCollectionDefaults()
  const analysis = createAnalysisDefaults()
  const notification = createNotificationDefaults()
  return {
    id: crypto.randomUUID(),
    name: '',
    sources: collection.sources,
    analyses: analysis.analyses,
    fan_in: null,
    system_prompt: '',
    input_prompt: '{input}',
    channels: notification.channels,
    source_overrides: collection.source_overrides,
    channel_overrides: notification.channel_overrides,
    input_separator: collection.input_separator,
    input_processing: collection.input_processing,
    collection_concurrency: collection.collection_concurrency,
    analysis_concurrency: analysis.analysis_concurrency,
    on_all_empty: collection.on_all_empty,
    analysis_failure: analysis.analysis_failure,
    send_partial: notification.send_partial,
    schedule: { type: 'cron', expression: DEFAULT_DAILY_CRON, timezone: null },
    enabled: true,
    backup: createBackupPolicy(),
  }
}

export function cloneWorkflow(value: WorkflowDefinition): WorkflowDefinition {
  return structuredClone(value)
}
