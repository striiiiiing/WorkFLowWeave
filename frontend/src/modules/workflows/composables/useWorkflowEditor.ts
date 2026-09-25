import { computed, ref, shallowRef, toValue, watch, type MaybeRefOrGetter, type Ref } from 'vue'
import { useAsyncTask } from '@/shared/async/useAsyncTask'
import type { JsonObject } from '@/shared/types'
import type { SourceConfig, SourceConfigEditorGateway } from '@/modules/resources/public'
import {
  addAnalysis,
  addSource,
  enableFanIn,
  moveSource,
  removeAnalysis,
  renameAnalysis,
  restoreSource,
  setChannelIds,
  setChannelOverride,
  setDetachedSource,
  setFanIn,
  setSourceOverride,
  setSources,
  updateAnalysis,
  updateBackup as updateBackupPolicy,
  updateWorkflow,
} from '../model/actions'
import { cloneWorkflow, createFanIn, createWorkflow } from '../model/defaults'
import { validateAnalysisId } from '../model/validation'
import type { AnalysisTask, BackupPolicy, FanInConfig, WorkflowDefinition } from '../model/types'

export interface WorkflowEditorOptions {
  identity: MaybeRefOrGetter<string | undefined>
  data?: Readonly<Ref<WorkflowDefinition | undefined>>
}

export function useWorkflowEditor(options: WorkflowEditorOptions) {
  const identity = computed(() => toValue(options.identity))
  const draft = shallowRef<WorkflowDefinition>()
  const disabledFanIn = shallowRef<FanInConfig | null>(null)
  const analysisDraftIds = ref<Record<number, string>>({})
  const sourceAction = useAsyncTask()
  let activeIdentity = identity.value
  let waitingForIdentity = activeIdentity !== undefined
  let initialSnapshot: WorkflowDefinition | undefined
  let sourceGeneration = 0

  function resetForIdentity(nextIdentity: string | undefined) {
    sourceGeneration += 1
    activeIdentity = nextIdentity
    waitingForIdentity = nextIdentity !== undefined
    disabledFanIn.value = null
    analysisDraftIds.value = {}
    if (nextIdentity === undefined) {
      const next = createWorkflow()
      draft.value = next
      initialSnapshot = cloneWorkflow(next)
    } else {
      draft.value = undefined
      initialSnapshot = undefined
    }
  }

  function acceptServer(value: WorkflowDefinition | undefined) {
    if (!value || !waitingForIdentity || value.id !== activeIdentity) return
    const next = cloneWorkflow(value)
    draft.value = next
    initialSnapshot = cloneWorkflow(next)
    waitingForIdentity = false
  }

  watch(identity, resetForIdentity, { immediate: true })
  watch(() => options.data?.value, acceptServer, { immediate: true })

  function replace(next: WorkflowDefinition) {
    draft.value = cloneWorkflow(next)
  }
  function requireDraft() {
    if (!draft.value) throw new Error('工作流尚未加载')
    return draft.value
  }
  function apply(next: WorkflowDefinition) {
    replace(next)
    return draft.value!
  }

  function update(changes: Parameters<typeof updateWorkflow>[1]) {
    return apply(updateWorkflow(requireDraft(), changes))
  }
  function setIdentity(value: string) {
    return apply({ ...requireDraft(), id: value })
  }
  function ensureId() {
    const value = requireDraft()
    if (value.id) return value.id
    const id = crypto.randomUUID()
    apply({ ...value, id })
    return id
  }
  function setSourceIds(ids: readonly string[]) {
    return apply(setSources(requireDraft(), ids))
  }
  function reorderSource(index: number, delta: number) {
    return apply(moveSource(requireDraft(), index, delta))
  }
  function addSourceId(id: string) {
    return apply(addSource(requireDraft(), id))
  }
  function applySource(sourceId: string, value: SourceConfig) {
    return apply(
      setSourceOverride(requireDraft(), sourceId, {
        source: structuredClone(value),
        options: {},
        setters: {},
        template: null,
      }),
    )
  }
  function setSource(sourceId: string, value: Parameters<typeof setSourceOverride>[2]) {
    return apply(setSourceOverride(requireDraft(), sourceId, value))
  }
  function restoreSharedSource(sourceId: string) {
    return apply(restoreSource(requireDraft(), sourceId))
  }
  async function detachSource(sourceId: string, gateway: SourceConfigEditorGateway) {
    const generation = sourceGeneration
    const workflowId = requireDraft().id
    const override = requireDraft().source_overrides[sourceId]
    return sourceAction.run(async () => {
      const value = await gateway.resolve(sourceId, override)
      if (generation !== sourceGeneration || requireDraft().id !== workflowId)
        throw new Error('工作流已切换，请重新操作数据源')
      return apply(setDetachedSource(requireDraft(), value))
    })
  }
  async function publishSource(
    sourceId: string,
    gateway: SourceConfigEditorGateway,
    existing: boolean,
    afterSave?: () => Promise<void> | void,
  ) {
    const generation = sourceGeneration
    const workflowId = requireDraft().id
    return sourceAction.run(async () => {
      const source = requireDraft().source_overrides[sourceId]?.source
      if (!source) throw new Error('当前来源没有可发布的独立配置')
      await gateway.save(
        { kind: 'shared-resource', resourceId: existing ? sourceId : source.id },
        structuredClone(source),
      )
      await afterSave?.()
      if (generation !== sourceGeneration || requireDraft().id !== workflowId)
        throw new Error('共用数据源已保存；工作流已切换，请检查当前草稿')
      apply(restoreSource(requireDraft(), sourceId))
      return source
    })
  }
  function addTask() {
    return apply(addAnalysis(requireDraft()))
  }
  function updateTask(index: number, changes: Partial<AnalysisTask>) {
    return apply(updateAnalysis(requireDraft(), index, changes))
  }
  function updateTaskId(index: number, value: string) {
    analysisDraftIds.value = { ...analysisDraftIds.value, [index]: value }
    const result = renameAnalysis(requireDraft(), index, value)
    if (result.error) return result.error
    const next = { ...analysisDraftIds.value }
    delete next[index]
    analysisDraftIds.value = next
    apply(result.workflow)
    return ''
  }
  function taskIdError(index: number) {
    const value = analysisDraftIds.value[index]
    return value === undefined ? '' : validateAnalysisId(requireDraft(), index, value)
  }
  function deleteTask(index: number) {
    const next = apply(removeAnalysis(requireDraft(), index))
    const nextIds: Record<number, string> = {}
    Object.entries(analysisDraftIds.value).forEach(([key, value]) => {
      const oldIndex = Number(key)
      if (oldIndex < index) nextIds[oldIndex] = value
      if (oldIndex > index) nextIds[oldIndex - 1] = value
    })
    analysisDraftIds.value = nextIds
    return next
  }
  function toggleFanIn(enabled: boolean) {
    if (enabled) {
      const next = enableFanIn(requireDraft(), disabledFanIn.value)
      disabledFanIn.value = null
      return apply(next)
    }
    disabledFanIn.value = requireDraft().fan_in
      ? cloneWorkflow({ ...requireDraft(), fan_in: requireDraft().fan_in }).fan_in
      : null
    return apply(setFanIn(requireDraft(), null))
  }
  function updateFanIn(changes: Partial<FanInConfig>) {
    const current = requireDraft().fan_in
    return current ? apply(setFanIn(requireDraft(), { ...current, ...changes })) : requireDraft()
  }
  function setChannels(ids: readonly string[]) {
    return apply(setChannelIds(requireDraft(), ids))
  }
  function toggleChannelOverride(id: string, enabled: boolean) {
    return apply(setChannelOverride(requireDraft(), id, enabled ? { options: {} } : null))
  }
  function updateChannelOptions(id: string, options: JsonObject) {
    const current = requireDraft().channel_overrides[id]
    if (!current) return requireDraft()
    return apply(setChannelOverride(requireDraft(), id, { ...current, options }))
  }
  function updateBackup(changes: Partial<BackupPolicy>) {
    return apply(updateBackupPolicy(requireDraft(), changes))
  }
  const dirty = computed(() => {
    if (!draft.value || !initialSnapshot) return false
    return JSON.stringify(draft.value) !== JSON.stringify(initialSnapshot)
  })

  return {
    draft: computed(() => draft.value),
    ready: computed(() => draft.value !== undefined && !waitingForIdentity),
    dirty,
    sourcePending: sourceAction.pending,
    sourceError: sourceAction.error,
    analysisDraftIds: computed(() => analysisDraftIds.value),
    requireDraft,
    replace,
    update,
    setIdentity,
    ensureId,
    setSourceIds,
    reorderSource,
    addSourceId,
    setSource,
    applySource,
    restoreSharedSource,
    detachSource,
    publishSource,
    addTask,
    updateTask,
    updateTaskId,
    taskIdError,
    deleteTask,
    toggleFanIn,
    updateFanIn,
    setChannels,
    toggleChannelOverride,
    updateChannelOptions,
    updateBackup,
    createFanIn,
  }
}

export type WorkflowEditorController = ReturnType<typeof useWorkflowEditor>
