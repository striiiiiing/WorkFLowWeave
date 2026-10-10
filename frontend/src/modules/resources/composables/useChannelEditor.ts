import { computed, onScopeDispose, ref, shallowRef, toRaw, watch } from 'vue'
import { useResourcesApi } from '../api/dependencies'
import type { ChannelConnectionStatus, ResourcesApi } from '../api/resourcesApi'
import { useAsyncTask } from '@/shared/async/useAsyncTask'
import {
  createResource,
  credentialPropertyNames,
  generatedResourceId,
  requiredCredentialPropertyNames,
  credentialDraftSchema,
} from '../model/public'
import { optionSchema } from '@/shared/schema/capabilities'
import { createFieldRule } from '@/shared/schema/schemaValidation'
import type { ChannelConfig } from '../model/public'
import type { SchemaCapability } from '@/shared/schema/types'

const CONNECTION_POLL_INTERVAL_MS = 1000
const CONNECTION_WAIT_TIMEOUT_MS = 300_000

function accountOptions(
  options: ChannelConfig['options'],
  capability: SchemaCapability | undefined,
) {
  const properties = (capability?.options_schema.properties ?? {}) as Record<
    string,
    Record<string, unknown>
  >
  return Object.fromEntries(
    Object.entries(options)
      .filter(([name]) => properties[name]?.['x-workflowweave-workflow'] !== true)
      .sort(([left], [right]) => left.localeCompare(right)),
  )
}

export function useChannelEditor(
  props: { initial?: ChannelConfig; capabilities: readonly SchemaCapability[] },
  resourcesApi: Pick<
    ResourcesApi,
    | 'create'
    | 'replace'
    | 'protectCredential'
    | 'startChannelConnection'
    | 'channelConnection'
    | 'cancelChannelConnection'
    | 'get'
  > = useResourcesApi(),
) {
  const initialDraft = props.initial
    ? structuredClone(toRaw(props.initial))
    : (createResource('channels') as ChannelConfig)
  const draft = shallowRef(initialDraft)
  const persisted = shallowRef<ChannelConfig | undefined>(props.initial)
  const generatedId = ref(!props.initial)
  const save = useAsyncTask()
  const connection = shallowRef<ChannelConnectionStatus>()
  const connectionPending = ref(false)
  const connectionError = ref('')
  const connectionReady = ref(false)
  const finishRequired = ref(false)
  const needsReconnect = ref(false)
  const isPersisted = computed(() => persisted.value !== undefined)
  const connectionLoading = ref(false)
  const capabilities = computed(() => props.capabilities)
  const capabilityName = computed(() => draft.value.channel)
  const capability = computed(() =>
    capabilities.value.find((item) => item.name === capabilityName.value),
  )
  const resourceSchema = computed(() => optionSchema(capability.value?.options_schema, 'resource'))
  const optionParameterSchema = computed(() => credentialDraftSchema(resourceSchema.value))
  const credentialNames = computed(() => credentialPropertyNames(capability.value?.options_schema))
  const requiredCredentialNames = computed(() =>
    requiredCredentialPropertyNames(capability.value?.options_schema),
  )
  const requiresFirstMessage = computed(
    () => capability.value?.options_schema['x-workflowweave-first-message'] === true
      && !draft.value.agent_enabled,
  )
  let connectionGeneration = 0
  let connectionId: string | undefined
  let pollTimer: ReturnType<typeof setTimeout> | undefined
  let wakePoll: (() => void) | undefined
  let cancelRequest: Promise<void> = Promise.resolve()
  let disposed = false
  let savedAccountSignature = JSON.stringify(accountOptions(initialDraft.options, capability.value))

  const isWaiting = () =>
    connection.value?.state === 'connecting' || connection.value?.state === 'waiting_message'

  function finishPollWait() {
    clearTimeout(pollTimer)
    pollTimer = undefined
    const wake = wakePoll
    wakePoll = undefined
    wake?.()
  }

  async function cancelConnection(reason: string, resetConnected = false) {
    if (!connectionId || (!isWaiting() && !resetConnected)) {
      return
    }
    const id = connectionId
    const generation = ++connectionGeneration
    finishPollWait()
    connectionPending.value = false
    connectionLoading.value = false
    connectionReady.value = false
    finishRequired.value = false
    connectionError.value = ''
    connection.value = {
      channel_id: id,
      state: 'cancelled',
      message: reason,
      error: null,
      target_options: {},
    }
    const task = resourcesApi
      .cancelChannelConnection(id)
      .then(() => undefined)
      .catch((cause: unknown) => {
        if (!disposed && generation === connectionGeneration) {
          connectionError.value = cause instanceof Error ? cause.message : String(cause)
        }
      })
    cancelRequest = task
    await task
  }

  async function readConnectedResource(
    id: string,
    status: ChannelConnectionStatus,
    generation: number,
  ) {
    const saved = await resourcesApi.get('channels', id)
    if (disposed || generation !== connectionGeneration) return
    persisted.value = saved
    draft.value = saved
    connection.value = status
    connectionReady.value = true
    finishRequired.value = true
    savedAccountSignature = JSON.stringify(accountOptions(saved.options, capability.value))
    needsReconnect.value = false
  }

  function acceptConnection(status: ChannelConnectionStatus, id: string, generation: number) {
    if (disposed || generation !== connectionGeneration || id !== connectionId) return false
    connection.value = status
    connectionError.value = status.error?.message ?? ''
    if (status.state === 'connected') {
      connectionReady.value = false
      return true
    }
    return false
  }

  async function observeConnection(
    id: string,
    generation: number,
    initialStatus: ChannelConnectionStatus,
    startedAt = Date.now(),
  ) {
    let status = initialStatus
    let connected = acceptConnection(status, id, generation)
    while (!connected && (status.state === 'connecting' || status.state === 'waiting_message')) {
      if (Date.now() - startedAt >= CONNECTION_WAIT_TIMEOUT_MS) {
        await cancelConnection('等待首条私聊消息超时，请重新连接。')
        connectionError.value = '等待首条私聊消息超时，请重新连接。'
        return
      }
      await new Promise<void>((resolve) => {
        wakePoll = resolve
        pollTimer = setTimeout(() => {
          pollTimer = undefined
          wakePoll = undefined
          resolve()
        }, CONNECTION_POLL_INTERVAL_MS)
      })
      if (disposed || generation !== connectionGeneration) return
      status = await resourcesApi.channelConnection(id)
      connected = acceptConnection(status, id, generation)
    }
    if (connected) await readConnectedResource(id, status, generation)
  }

  async function waitForConnection(id: string, generation: number) {
    const startedAt = Date.now()
    const status = await resourcesApi.startChannelConnection(id)
    if (disposed || generation !== connectionGeneration) {
      await resourcesApi.cancelChannelConnection(id)
      return
    }
    await observeConnection(id, generation, status, startedAt)
  }

  async function monitorConnection(id: string, initialStatus: ChannelConnectionStatus) {
    const generation = ++connectionGeneration
    connectionId = id
    connectionPending.value = true
    connection.value = initialStatus
    try {
      await observeConnection(id, generation, initialStatus)
    } catch (cause) {
      if (!disposed && generation === connectionGeneration) {
        connectionError.value = cause instanceof Error ? cause.message : String(cause)
      }
    } finally {
      if (!disposed && generation === connectionGeneration) connectionPending.value = false
    }
  }

  async function startConnection(id: string, restart = false) {
    await cancelRequest
    if (
      restart &&
      (connection.value?.state === 'connected' ||
        connection.value?.state === 'failed' ||
        connection.value?.state === 'cancelled')
    ) {
      await cancelConnection('正在重新连接。', true)
    }
    const generation = ++connectionGeneration
    connectionId = id
    connectionPending.value = true
    connectionReady.value = false
    finishRequired.value = true
    connectionError.value = ''
    connection.value = {
      channel_id: id,
      state: 'connecting',
      message: '正在连接渠道。',
      error: null,
      target_options: {},
    }
    try {
      await waitForConnection(id, generation)
    } catch (cause) {
      if (!disposed && generation === connectionGeneration) {
        connectionError.value = cause instanceof Error ? cause.message : String(cause)
      }
    } finally {
      if (!disposed && generation === connectionGeneration) connectionPending.value = false
    }
  }

  if (
    props.initial &&
    requiresFirstMessage.value &&
    props.initial.enabled
  ) {
    const initialId = props.initial.id
    const generation = ++connectionGeneration
    connectionId = initialId
    connectionLoading.value = true
    void resourcesApi
      .channelConnection(initialId)
      .then((status) => {
        if (!disposed && generation === connectionGeneration) {
          connectionLoading.value = false
          connection.value = status
          connectionError.value = status.error?.message ?? ''
          if (status.state === 'connected') connectionReady.value = true
          if (status.state === 'connecting' || status.state === 'waiting_message') {
            void monitorConnection(initialId, status)
          }
        }
      })
      .catch((cause: unknown) => {
        if (!disposed && generation === connectionGeneration) {
          connectionLoading.value = false
          connectionError.value = cause instanceof Error ? cause.message : String(cause)
        }
      })
  }

  watch(
    () => draft.value.channel,
    (next, previous) => {
      if (next !== previous) void cancelConnection('渠道已修改，等待连接已取消。', true)
    },
  )
  function updateId(value: string) {
    draft.value = { ...draft.value, id: value }
    generatedId.value = false
  }
  watch(capabilityName, (next, previous) => {
    if (next === previous) return
    draft.value = {
      ...draft.value,
      agent_enabled: false,
      id:
        !props.initial && generatedId.value
          ? generatedResourceId(capability.value?.id_prefix)
          : draft.value.id,
      options: {},
    }
  })
  function submit(validate: () => Promise<boolean>) {
    return save.run(async () => {
      if (!(await validate())) throw new Error('请检查表单中的错误')
      for (const name of requiredCredentialNames.value) {
        if (!draft.value.options[name]) throw new Error(`请填写必填凭据「${name}」`)
      }
      const value = structuredClone(toRaw(draft.value))
      for (const name of credentialNames.value) {
        const credential = value.options[name]
        if (typeof credential === 'string') {
          value.options[name] = await resourcesApi.protectCredential(credential)
        }
      }
      const error = createFieldRule(resourceSchema.value).validate(value.options)
      if (error) throw new Error(error)
      value.id ||= generatedResourceId(capability.value?.id_prefix)
      const existing = persisted.value ?? props.initial
      const saved = existing
        ? await resourcesApi.replace('channels', existing.id, value)
        : await resourcesApi.create('channels', value)
      persisted.value = saved
      draft.value = saved
      savedAccountSignature = JSON.stringify(accountOptions(saved.options, capability.value))
      return saved
    })
  }

  function updateOptions(options: ChannelConfig['options']) {
    const previous = JSON.stringify(accountOptions(draft.value.options, capability.value))
    const next = JSON.stringify(accountOptions(options, capability.value))
    draft.value = { ...draft.value, options }
    if (previous !== next) {
      needsReconnect.value = next !== savedAccountSignature
      void cancelConnection('账号参数已修改，等待连接已取消。', true)
    }
  }

  function updateEnabled(enabled: boolean) {
    draft.value = { ...draft.value, enabled }
    if (!enabled && (isWaiting() || connectionLoading.value)) {
      void cancelConnection('渠道已停用，等待连接已取消。', connectionLoading.value)
    }
  }

  async function finishConnection() {
    if (!connectionReady.value || connection.value?.state !== 'connected') return undefined
    finishRequired.value = false
    return persisted.value
  }

  async function completeConnection() {
    const value = await finishConnection()
    if (!value) return undefined
    connectionReady.value = false
    return value
  }

  onScopeDispose(() => {
    disposed = true
    if (isWaiting() || connectionLoading.value) {
      void cancelConnection('编辑器已关闭，等待连接已取消。', connectionLoading.value)
    }
  })

  return {
    draft: computed<Readonly<ChannelConfig>>(() => draft.value),
    updateChannel: (channel: string) => {
      draft.value = { ...draft.value, channel }
    },
    updateEnabled,
    updateAgentEnabled: (enabled: boolean) => {
      draft.value = { ...draft.value, agent_enabled: enabled }
      if (enabled && (isWaiting() || connectionLoading.value)) {
        void cancelConnection('已切换为双向对话，首次单向连接已取消。')
      }
    },
    updateOptions,
    updateAdvanced: (fields: Partial<Pick<ChannelConfig, 'timeout'>>) => {
      draft.value = { ...draft.value, ...fields }
    },
    save,
    capabilities,
    capabilityName,
    capability,
    optionParameterSchema,
    updateId,
    submit,
    startConnection,
    monitorConnection,
    connection,
    connectionPending,
    connectionError,
    connectionReady,
    finishRequired,
    isPersisted,
    needsReconnect,
    requiresFirstMessage,
    cancelConnection,
    finishConnection: completeConnection,
  }
}
