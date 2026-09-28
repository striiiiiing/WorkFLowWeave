import { computed, nextTick, readonly, ref, watch, type Ref } from 'vue'
import { useQuery } from '@/shared/async/useQuery'
import { useRunsApi } from '../api/dependencies'
import type { ResumeOptions, RunsApi } from '../api/runsApi'
import type { WorkflowStage } from '../model/types'
import { sessionStates, stages } from '../model/session'
import { useSession } from './useSession'
import { usePhaseReport } from './usePhaseReport'
import { useCancelAction, useRecoveryAction } from './useRunActions'

export function useRunDetail(
  id: Ref<string>,
  api: Pick<RunsApi, 'get' | 'phase' | 'recovery' | 'cancel'> &
    Partial<Pick<RunsApi, 'subscribe' | 'resume' | 'recover'>> = useRunsApi(),
) {
  const session = useSession(id, api)
  const active = computed(() =>
    session.data.value ? sessionStates[session.data.value.status].active : false,
  )
  const selectedStage = ref<Exclude<WorkflowStage, 'finish'>>('collect')
  const stageRecoveryEnabled = ref(false)
  const recovery = useQuery(
    async (signal) => {
      if (!session.data.value || active.value) return undefined
      return api.recovery(id.value, {}, signal)
    },
    [id, () => session.data.value?.version, active],
  )
  const stageRecovery = useQuery(
    async (signal) => {
      if (!stageRecoveryEnabled.value || !session.data.value || active.value) return undefined
      return api.recovery(id.value, { stage: selectedStage.value }, signal)
    },
    [id, () => session.data.value?.execution_epoch, active, selectedStage, stageRecoveryEnabled],
  )
  const phases = Object.fromEntries(
    stages.map((stage) => [
      stage.key,
      usePhaseReport(
        computed(() => {
          const record = session.data.value
          const artifact = record?.session_id === id.value
            ? record.artifacts.find((item) => item.stage === stage.key)
            : undefined
          return artifact?.availability === 'available' && artifact.content_version !== null
            ? { id: id.value, version: artifact.content_version, stage: stage.key }
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
    if (id.value !== sourceId || session.error.value) return
    const versionUnchanged = session.data.value?.version === version
    await Promise.all([
      ...(versionUnchanged ? [recovery.refresh()] : []),
      ...(stageRecoveryEnabled.value ? [stageRecovery.refresh()] : []),
      ...(versionUnchanged ? Object.values(phases).map((phase) => phase.refresh()) : []),
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
  async function resume(options: ResumeOptions = {}) {
    const sourceId = id.value
    actionError.value = ''
    const result = await recoveryAction.resume(sourceId, {
      ...options,
      request_id: options.request_id ?? crypto.randomUUID(),
    })
    if (id.value !== sourceId) return { status: 'busy' } as const
    if (result.status === 'unknown' || result.status === 'failure')
      actionError.value =
        (result.status === 'unknown' ? '执行请求结果未知，正在查询确认，请勿重复提交：' : '') +
        result.message
    if (result.status !== 'busy') await session.refresh()
    return result
  }
  return {
    session,
    active,
    recovery,
    stageRecovery,
    selectedStage,
    stageRecoveryEnabled,
    phases,
    loadedContext,
    actionError,
    actionPending,
    refreshAll,
    cancel,
    resume,
    recover: resume,
  }
}
