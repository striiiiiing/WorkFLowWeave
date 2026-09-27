import { computed, onScopeDispose, ref, toRaw, watch } from 'vue'
import { useResourcesApi } from '../api/dependencies'
import type { ResourcesApi } from '../api/resourcesApi'
import { useAsyncTask } from '@/shared/async/useAsyncTask'
import { useErrorFormatter } from '@/shared/async/errorFormatter'
import { createResource, generatedResourceId } from '../model/resources'
import type { AIConfig } from '../model/types'

export function useAIProviderEditor(
  props: { initial?: AIConfig },
  resourcesApi: Pick<
    ResourcesApi,
    'create' | 'replace' | 'protectCredential' | 'discoverAIModels'
  > = useResourcesApi(),
) {
  const initial = props.initial
    ? structuredClone(toRaw(props.initial))
    : (createResource('ai') as AIConfig)
  const draft = ref(initial)
  const persisted = ref(props.initial ? structuredClone(initial) : undefined)
  const save = useAsyncTask()
  const health = { pending: ref(false), error: ref('') }
  const formatError = useErrorFormatter()
  const plaintext = ref('')
  const credentialMode = ref<'keep' | 'input' | 'env' | 'none'>(props.initial ? 'keep' : 'input')
  const environmentName = ref(initial.api_key?.kind === 'env' ? initial.api_key.name : '')
  const discovered = ref<string[]>([])
  const checked = ref(false)
  const busy = computed(() => save.pending.value)
  let discoveryVersion = 0
  watch(
    () => [
      draft.value.base_url,
      draft.value.provider,
      draft.value.api_key,
      draft.value.timeout,
      draft.value.retries,
      credentialMode.value,
      environmentName.value,
      plaintext.value,
    ],
    () => {
      discoveryVersion++
      checked.value = false
      discovered.value = []
      health.pending.value = false
      health.error.value = ''
    },
  )
  onScopeDispose(() => {
    discoveryVersion++
  })

  async function discoverModels() {
    const version = ++discoveryVersion
    checked.value = false
    discovered.value = []
    health.error.value = ''
    health.pending.value = true
    try {
      // The draft contains Vue proxies; the API accepts JSON, so snapshot that exact payload.
      const config = JSON.parse(JSON.stringify(draft.value)) as AIConfig
      if (!config.base_url) throw new Error('请先填写服务地址')
      if (credentialMode.value === 'input') {
        if (!plaintext.value) throw new Error('请先填写 API 密钥')
        config.api_key = await resourcesApi.protectCredential(plaintext.value)
      } else if (credentialMode.value === 'env') {
        if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(environmentName.value)) {
          throw new Error('请输入有效环境变量名称')
        }
        config.api_key = { kind: 'env', name: environmentName.value }
      } else if (credentialMode.value === 'none') {
        config.api_key = null
      }
      if (version !== discoveryVersion) return
      const models = await resourcesApi.discoverAIModels(config)
      if (version !== discoveryVersion) return
      discovered.value = models
      checked.value = true
    } catch (cause) {
      if (version === discoveryVersion) health.error.value = formatError(cause)
    } finally {
      if (version === discoveryVersion) health.pending.value = false
    }
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
    plaintext,
    credentialMode,
    environmentName,
    discovered,
    checked,
    busy,
    discoverModels,
    submit,
  }
}
