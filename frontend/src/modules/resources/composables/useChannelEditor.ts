import { computed, ref, shallowRef, toRaw, watch } from 'vue'
import { useResourcesApi } from '../api/dependencies'
import type { ResourcesApi } from '../api/resourcesApi'
import { useAsyncTask } from '@/shared/async/useAsyncTask'
import { createResource, credentialPropertyNames, generatedResourceId } from '../model/public'
import { optionSchema } from '@/shared/schema/capabilities'
import type { Credential, ChannelConfig } from '../model/public'
import type { SchemaCapability } from '@/shared/schema/types'
export function useChannelEditor(
  props: { initial?: ChannelConfig; capabilities: readonly SchemaCapability[] },
  resourcesApi: Pick<ResourcesApi, 'create' | 'replace' | 'protectCredential'> = useResourcesApi(),
) {
  const initialDraft = props.initial
    ? structuredClone(toRaw(props.initial))
    : (createResource('channels') as ChannelConfig)
  const draft = shallowRef(initialDraft)
  const generatedId = ref(!props.initial)
  const save = useAsyncTask()
  const capabilities = computed(() => props.capabilities)
  const capabilityName = computed(() => draft.value.channel)
  const capability = computed(() =>
    capabilities.value.find((item) => item.name === capabilityName.value),
  )
  const optionParameterSchema = computed(() =>
    optionSchema(capability.value?.options_schema, 'resource'),
  )
  const credentialNames = computed(() => credentialPropertyNames(capability.value?.options_schema))
  function credentialValue(name: string): Credential | null {
    const value = draft.value.options[name]
    return value && typeof value === 'object' && !Array.isArray(value)
      ? (value as Credential)
      : null
  }
  function updateCredential(name: string, value: Credential | null) {
    draft.value = { ...draft.value, options: { ...draft.value.options, [name]: value } }
  }
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
      const value = structuredClone(toRaw(draft.value))
      value.id ||= generatedResourceId(capability.value?.id_prefix)
      const saved = props.initial
        ? await resourcesApi.replace('channels', props.initial.id, value)
        : await resourcesApi.create('channels', value)
      return saved
    })
  }

  return {
    draft: computed<Readonly<ChannelConfig>>(() => draft.value),
    updateChannel: (channel: string) => {
      draft.value = { ...draft.value, channel }
    },
    updateEnabled: (enabled: boolean) => {
      draft.value = { ...draft.value, enabled }
    },
    updateAgentEnabled: (enabled: boolean) => {
      draft.value = { ...draft.value, agent_enabled: enabled }
    },
    updateOptions: (options: ChannelConfig['options']) => {
      draft.value = { ...draft.value, options }
    },
    updateAdvanced: (fields: Partial<Pick<ChannelConfig, 'timeout'>>) => {
      draft.value = { ...draft.value, ...fields }
    },
    save,
    capabilities,
    capabilityName,
    capability,
    optionParameterSchema,
    credentialNames,
    credentialValue,
    updateCredential,
    updateId,
    submit,
    protect: resourcesApi.protectCredential,
  }
}
