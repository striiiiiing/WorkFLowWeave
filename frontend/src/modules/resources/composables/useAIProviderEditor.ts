import { computed, ref, toRaw, watch } from 'vue'
import { useResourcesApi } from '../api/dependencies'
import type { ResourcesApi } from '../api/resourcesApi'
import { useAsyncTask } from '@/shared/async/useAsyncTask'
import { createResource, generatedResourceId } from '../model/resources'
import type { AIConfig } from '../model/types'

export function useAIProviderEditor(
  props: { initial?: AIConfig },
  resourcesApi: Pick<
    ResourcesApi,
    'create' | 'replace' | 'protectCredential' | 'checkAIConnection' | 'testAIModel'
  > = useResourcesApi(),
) {
  const initial = props.initial
    ? structuredClone(toRaw(props.initial))
    : (createResource('ai') as AIConfig)
  const draft = ref(initial)
  const persisted = ref(props.initial ? structuredClone(initial) : undefined)
  const save = useAsyncTask()
  const health = useAsyncTask()
  const modelTest = useAsyncTask()
  const testedModel = ref('')
  const plaintext = ref('')
  const credentialMode = ref<'keep' | 'input' | 'env' | 'none'>(props.initial ? 'keep' : 'input')
  const environmentName = ref(initial.api_key?.kind === 'env' ? initial.api_key.name : '')
  const discovered = ref<string[]>([])
  const checked = ref(false)
  const busy = computed(() => save.pending.value || health.pending.value || modelTest.pending.value)
  const connectionChanged = computed(
    () =>
      !persisted.value ||
      draft.value.base_url !== persisted.value.base_url ||
      draft.value.provider !== persisted.value.provider ||
      JSON.stringify(draft.value.api_key) !== JSON.stringify(persisted.value.api_key) ||
      credentialMode.value !== 'keep',
  )
  watch(
    () => [
      draft.value.base_url,
      draft.value.provider,
      credentialMode.value,
      environmentName.value,
      plaintext.value,
    ],
    () => {
      checked.value = false
      discovered.value = []
      health.error.value = ''
      modelTest.error.value = ''
      testedModel.value = ''
    },
  )
  function checkHealth() {
    if (!persisted.value || connectionChanged.value || busy.value) return
    const id = persisted.value.id
    checked.value = false
    discovered.value = []
    void health.run(async () => {
      discovered.value = await resourcesApi.checkAIConnection(id)
      checked.value = true
    })
  }
  async function testModel(model: string) {
    if (!persisted.value || connectionChanged.value || busy.value) return
    testedModel.value = ''
    const result = await modelTest.run(async () => {
      const result = await resourcesApi.testAIModel(persisted.value!.id, model)
      if (result.status !== 'success') {
        throw new Error(result.error?.message ?? `模型“${model}”没有正常返回结果`)
      }
      return result
    })
    if (result.status === 'success') testedModel.value = model
  }
  async function submit(validate: () => Promise<boolean>) {
    if (busy.value) return { status: 'busy' as const }
    return save.run(async () => {
      if (!(await validate())) {
        throw new Error('请检查表单中的错误；模型参数错误可在“配置参数”中修改。')
      }
      // Only top-level fields change here; the HTTP boundary serializes nested Vue proxies as JSON.
      const value = { ...draft.value }
      value.id ||= generatedResourceId()
      if (credentialMode.value === 'input') {
        value.api_key = await resourcesApi.protectCredential(plaintext.value)
        draft.value.api_key = value.api_key
        plaintext.value = ''
        credentialMode.value = 'keep'
      } else if (credentialMode.value !== 'keep') {
        value.api_key =
          credentialMode.value === 'none' ? null : { kind: 'env', name: environmentName.value }
      }
      const result = persisted.value
        ? await resourcesApi.replace('ai', persisted.value.id, value)
        : await resourcesApi.create('ai', value)
      draft.value = structuredClone(result)
      persisted.value = structuredClone(result)
      credentialMode.value = 'keep'
      return result
    })
  }

  return {
    draft: computed<Readonly<AIConfig>>(() => draft.value),
    updateConnection: (fields: Partial<Pick<AIConfig, 'provider' | 'base_url'>>) => {
      draft.value = { ...draft.value, ...fields }
    },
    updateId: (id: string) => {
      draft.value.id = id
    },
    updateModels: (models: AIConfig['models']) => {
      draft.value.models = models
    },
    updateAdvanced: (fields: Partial<Pick<AIConfig, 'timeout' | 'retries'>>) => {
      draft.value = { ...draft.value, ...fields }
    },
    persisted,
    save,
    health,
    modelTest,
    testedModel,
    plaintext,
    credentialMode,
    environmentName,
    discovered,
    checked,
    busy,
    connectionChanged,
    checkHealth,
    testModel,
    submit,
  }
}
