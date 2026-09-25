import { computed } from 'vue'
import { useWorkflowList, sourceUsage, type WorkflowDefinition } from '@/modules/workflows/public'
import type { SourceUsageView } from '@/modules/resources/public'

export function useSourceUsage(
  options: {
    query?: ReturnType<typeof useWorkflowList>
    currentDraft?: () => WorkflowDefinition | undefined
  } = {},
) {
  const query = options.query ?? useWorkflowList()
  // A failed refresh means usage is unknown even when a stale list is retained.
  const known = computed(() => !query.error.value && query.data.value !== undefined)
  function references(id: string): SourceUsageView[] | undefined {
    if (!known.value) return undefined
    const current = options.currentDraft?.()
    const workflows = current
      ? [...query.data.value!.filter((item) => item.id !== current.id), current]
      : query.data.value!
    return sourceUsage(id, workflows)
  }
  return { ...query, known, references }
}
