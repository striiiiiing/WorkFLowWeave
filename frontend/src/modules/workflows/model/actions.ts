import { cloneWorkflow, createFanIn } from './defaults'
import { validateAnalysisId } from './validation'
import type { AnalysisTask, BackupPolicy, FanInConfig, WorkflowDefinition } from './types'
import type {
  ChannelOverride as ResourceChannelOverride,
  SourceConfig,
  SourceOverride,
} from '@/modules/resources/public'

export type WorkflowChanges = Partial<
  Pick<
    WorkflowDefinition,
    | 'name'
    | 'enabled'
    | 'interval_seconds'
    | 'input_separator'
    | 'include_counts'
    | 'collection_concurrency'
    | 'analysis_concurrency'
    | 'on_all_empty'
    | 'analysis_failure'
    | 'send_partial'
  >
>

export function updateWorkflow(workflow: WorkflowDefinition, changes: WorkflowChanges) {
  return { ...cloneWorkflow(workflow), ...changes }
}

export function setSources(workflow: WorkflowDefinition, sources: readonly string[]) {
  const next = [...new Set(sources)]
  const source_overrides = Object.fromEntries(
    Object.entries(workflow.source_overrides).filter(([id]) => next.includes(id)),
  )
  return { ...cloneWorkflow(workflow), sources: next, source_overrides }
}

export function moveSource(workflow: WorkflowDefinition, index: number, delta: number) {
  const sources = [...workflow.sources]
  const target = index + delta
  if (index < 0 || target < 0 || target >= sources.length) return cloneWorkflow(workflow)
  ;[sources[index], sources[target]] = [sources[target], sources[index]]
  return { ...cloneWorkflow(workflow), sources }
}

export function setSourceOverride(
  workflow: WorkflowDefinition,
  sourceId: string,
  override: SourceOverride,
) {
  return {
    ...cloneWorkflow(workflow),
    source_overrides: { ...workflow.source_overrides, [sourceId]: structuredClone(override) },
  }
}

export function setDetachedSource(workflow: WorkflowDefinition, source: SourceConfig) {
  return setSourceOverride(workflow, source.id, {
    source: structuredClone(source),
    options: {},
    setters: {},
    template: null,
  })
}

export function restoreSource(workflow: WorkflowDefinition, sourceId: string) {
  const source_overrides = { ...workflow.source_overrides }
  delete source_overrides[sourceId]
  return { ...cloneWorkflow(workflow), source_overrides }
}

export function addSource(workflow: WorkflowDefinition, sourceId: string) {
  return workflow.sources.includes(sourceId)
    ? cloneWorkflow(workflow)
    : setSources(workflow, [...workflow.sources, sourceId])
}

export function addAnalysis(workflow: WorkflowDefinition): WorkflowDefinition {
  let index = workflow.analyses.length + 1
  while (workflow.analyses.some((task) => task.id === `task_${index}`)) index += 1
  const task: AnalysisTask = { id: `task_${index}`, ai: '', model: '', prompt: '{input}' }
  return { ...cloneWorkflow(workflow), analyses: [...workflow.analyses, task] }
}

export function updateAnalysis(
  workflow: WorkflowDefinition,
  index: number,
  changes: Partial<AnalysisTask>,
) {
  if (!workflow.analyses[index]) return cloneWorkflow(workflow)
  const analyses = workflow.analyses.map((task, taskIndex) =>
    taskIndex === index ? { ...task, ...changes } : { ...task },
  )
  return { ...cloneWorkflow(workflow), analyses }
}

export function renameAnalysis(
  workflow: WorkflowDefinition,
  index: number,
  id: string,
): { workflow: WorkflowDefinition; error: string } {
  const error = validateAnalysisId(workflow, index, id)
  if (error || !workflow.analyses[index]) return { workflow: cloneWorkflow(workflow), error }
  const previous = workflow.analyses[index].id
  const next = updateAnalysis(workflow, index, { id })
  if (!next.fan_in) return { workflow: next, error: '' }
  return {
    workflow: {
      ...next,
      fan_in: {
        ...next.fan_in,
        order: next.fan_in.order.map((entry) => (entry === previous ? id : entry)),
      },
    },
    error: '',
  }
}

export function removeAnalysis(workflow: WorkflowDefinition, index: number) {
  const task = workflow.analyses[index]
  if (!task) return cloneWorkflow(workflow)
  const next = {
    ...cloneWorkflow(workflow),
    analyses: workflow.analyses.filter((_entry, taskIndex) => taskIndex !== index),
  }
  return next.fan_in
    ? {
        ...next,
        fan_in: { ...next.fan_in, order: next.fan_in.order.filter((id) => id !== task.id) },
      }
    : next
}

export function setFanIn(workflow: WorkflowDefinition, fanIn: FanInConfig | null) {
  return { ...cloneWorkflow(workflow), fan_in: fanIn ? structuredClone(fanIn) : null }
}

export function enableFanIn(workflow: WorkflowDefinition, disabledDraft?: FanInConfig | null) {
  return setFanIn(workflow, disabledDraft ?? createFanIn())
}

export function setChannelIds(workflow: WorkflowDefinition, channels: readonly string[]) {
  const next = [...new Set(channels)]
  const channel_overrides = Object.fromEntries(
    Object.entries(workflow.channel_overrides).filter(([id]) => next.includes(id)),
  )
  return { ...cloneWorkflow(workflow), channels: next, channel_overrides }
}

export function setChannelOverride(
  workflow: WorkflowDefinition,
  channelId: string,
  override: ResourceChannelOverride | null,
) {
  const channel_overrides = { ...workflow.channel_overrides }
  if (override) channel_overrides[channelId] = structuredClone(override)
  else delete channel_overrides[channelId]
  return { ...cloneWorkflow(workflow), channel_overrides }
}

export function updateBackup(workflow: WorkflowDefinition, changes: Partial<BackupPolicy>) {
  return { ...cloneWorkflow(workflow), backup: { ...workflow.backup, ...changes } }
}
