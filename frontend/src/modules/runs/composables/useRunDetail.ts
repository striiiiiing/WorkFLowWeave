import { computed, nextTick, readonly, ref, shallowRef, watch, type Ref } from 'vue'
import { useQuery } from '@/shared/async/useQuery'
import { useRunsApi } from '../api/dependencies'
import type { ResumeOptions, RunsApi } from '../api/runsApi'
import type { WorkflowStage } from '../model/types'
import { sessionStates, stages } from '../model/session'
import { isTerminalStatus } from '../model/progress'
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
  const selectedStage = ref<NonNullable<ResumeOptions['stage']>>('collect')
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
  const phaseVersions = shallowRef<Partial<Record<WorkflowStage, number>>>({})
  let phaseIdentity: { sessionId: string; epoch: string | null } | undefined
  watch([id, () => session.data.value?.execution_epoch], () => {
    phaseVersions.value = {}
    phaseIdentity = undefined
  })
  watch(
    () => session.data.value,
    (record) => {
      if (!record || record.session_id !== id.value) return
      const identityChanged =
        phaseIdentity?.sessionId !== record.session_id ||
        phaseIdentity.epoch !== record.execution_epoch
      const versions = identityChanged
        ? (Object.fromEntries(stages.map(({ key }) => [key, record.version])) as Partial<
            Record<WorkflowStage, number>
          >)
        : { ...phaseVersions.value }
      phaseIdentity = { sessionId: record.session_id, epoch: record.execution_epoch }
      const setVersion = (stage: WorkflowStage, version: number) => {
        if ((versions[stage] ?? -1) < version) versions[stage] = version
      }
      for (const item of record.progress) {
        if (item.version === null) continue
        if (item.stage === 'analyze' && item.event === 'item') setVersion('collect', item.version)
        if (item.event === 'aggregate') {
          setVersion('collect', item.version)
          setVersion('analyze', item.version)
          setVersion('aggregate', item.version)
        }
      }
      if (isTerminalStatus(record.status)) {
        for (const { key } of stages) setVersion(key, record.version)
      }
      phaseVersions.value = versions
    },
    { immediate: true },
  )
  const phases = Object.fromEntries(
    stages.map((stage) => [
      stage.key,
      usePhaseReport(
        computed(() => {
          const record = session.data.value
          const version =
            record?.session_id === id.value ? phaseVersions.value[stage.key] : undefined
          return version !== undefined ? { id: id.value, version, stage: stage.key } : undefined
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
