import { computed, nextTick, readonly, ref, watch, type Ref } from 'vue'
import { useQuery } from '@/shared/async/useQuery'
import { useRunsApi } from '../api/dependencies'
import type { RunsApi } from '../api/runsApi'
import { sessionStates, stages } from '../model/session'
import { useSession } from './useSession'
import { usePhaseReport } from './usePhaseReport'
import { useCancelAction, useRecoveryAction } from './useRunActions'

export function useRunDetail(
  id: Ref<string>,
  api: Pick<RunsApi, 'get' | 'phase' | 'recovery' | 'recover' | 'cancel'> = useRunsApi(),
) {
  const session = useSession(id, api)
  const active = computed(() =>
    session.data.value ? sessionStates[session.data.value.status].active : false,
  )
  const recovery = useQuery(
    async (signal) => {
      if (!session.data.value || active.value) return undefined
      return api.recovery(id.value, signal)
    },
    [id, () => session.data.value?.version, active],
  )
  const phases = Object.fromEntries(
    stages.map((stage) => [
      stage.key,
      usePhaseReport(
        computed(() => {
          const record = session.data.value
          return record && record.session_id === id.value
            ? { id: id.value, version: record.version, stage: stage.key }
            : undefined
        }),
        api,
      ),
    ]),
  ) as Record<(typeof stages)[number]['key'], ReturnType<typeof usePhaseReport>>
  const actions = useCancelAction(api)
  const recoveryAction = useRecoveryAction(api)
  const actionError = ref('')
  watch(id, () => {
    actionError.value = ''
  })
  const actionPending = computed(() => actions.pending.value || recoveryAction.pending.value)
  const loadedContext = computed(() => {
    const record = session.data.value
    if (record?.session_id !== id.value) return undefined
    return readonly({
      session: record,
      phases: stages.map(({ key }) => ({
        stage: key,
        data: phases[key].data.value,
        parsed: phases[key].parsed.value,
        pending: phases[key].pending.value,
        error: phases[key].error.value,
        readAt: phases[key].readAt.value,
      })),
    })
  })
  async function refreshAll() {
    const sourceId = id.value
    const version = session.data.value?.version
    await session.refresh()
    await nextTick()
    // Version changes already invalidate recovery and every phase through their identity.
    if (id.value === sourceId && !session.error.value && session.data.value?.version === version)
      await Promise.all([
        recovery.refresh(),
        ...Object.values(phases).map((phase) => phase.refresh()),
      ])
  }
  async function cancel() {
    const sourceId = id.value
    actionError.value = ''
    const result = await actions.cancel(sourceId)
    if (id.value !== sourceId) return result
    if (result.status === 'unknown' || result.status === 'failure')
      actionError.value =
        (result.status === 'unknown' ? '取消结果未知，请刷新确认：' : '') + result.message
    if (result.status !== 'busy') await refreshAll()
    return result
  }
  async function recover() {
    const sourceId = id.value
    actionError.value = ''
    const result = await recoveryAction.recover(sourceId)
    if (id.value !== sourceId) return { status: 'busy' } as const
    if (result.status === 'unknown' || result.status === 'failure')
      actionError.value =
        (result.status === 'unknown' ? '恢复结果未知，请刷新确认：' : '') + result.message
    if (result.status === 'success' && result.value.session_id === sourceId) await refreshAll()
    else if (result.status !== 'busy') await recovery.refresh()
    return result
  }
  return {
    session,
    active,
    recovery,
    phases,
    loadedContext,
    actionError,
    actionPending,
    refreshAll,
    cancel,
    recover,
  }
}
