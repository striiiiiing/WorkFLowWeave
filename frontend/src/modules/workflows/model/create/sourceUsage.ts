import type { WorkflowDefinition } from './definition'

export function sourceUsage(sourceId: string, workflows: readonly WorkflowDefinition[]) {
  return workflows
    .filter((workflow) => workflow.sources.includes(sourceId))
    .map((workflow) => ({
      id: workflow.id,
      name: workflow.name || workflow.id,
      detached: !!workflow.source_overrides[sourceId]?.source,
    }))
}
