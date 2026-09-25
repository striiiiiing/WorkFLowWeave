import { computed, type Ref } from 'vue'
import { useQuery } from '@/shared/async/useQuery'
import { parsePhase } from '../model/report'
import type { WorkflowStage } from '../model/types'
import type { RunsApi } from '../api/runsApi'
import { useRunsApi } from '../api/dependencies'

export interface PhaseIdentity {
  id: string
  version: number
  stage: WorkflowStage
}
export function usePhaseReport(
  identity: Readonly<Ref<PhaseIdentity | undefined>>,
  api: Pick<RunsApi, 'phase'> = useRunsApi(),
) {
  const query = useQuery(
    async (signal) => {
      const key = identity.value
      return key ? api.phase(key.id, key.stage, key.version, signal) : undefined
    },
    [() => identity.value?.id, () => identity.value?.version, () => identity.value?.stage],
  )
  const parsed = computed(() => {
    if (query.data.value?.availability !== 'available' || !identity.value) return undefined
    try {
      return { result: parsePhase(identity.value.stage, query.data.value.content), error: '' }
    } catch (cause) {
      return { result: undefined, error: cause instanceof Error ? cause.message : String(cause) }
    }
  })
  const raw = computed(() => JSON.stringify(query.data.value?.content, null, 2))
  return { ...query, parsed, raw, identity }
}
export type PhaseReportController = ReturnType<typeof usePhaseReport>
