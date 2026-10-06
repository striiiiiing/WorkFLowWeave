import { computed, type Ref } from 'vue'
import { useQuery } from '@/shared/async/useQuery'
import { useAsyncTask } from '@/shared/async/useAsyncTask'
import { useResourcesApi } from '../api/dependencies'
import type { ResourcesApi } from '../api/resourcesApi'
import type { EditableKind } from '../model/public'
import type {
  SourceConfig,
  AIConfig,
  ChannelConfig,
  SourceConfigEditorGateway,
} from '../model/public'
export function useResourceList(
  kind: Readonly<Ref<EditableKind>>,
  api: ResourcesApi = useResourcesApi(),
) {
  const query = useQuery((signal) => api.list(kind.value, signal), [kind])
  const action = useAsyncTask()
  const sources = computed(() =>
    kind.value === 'sources' ? (query.data.value as SourceConfig[] | undefined) : undefined,
  )
  const providers = computed(() =>
    kind.value === 'ai' ? (query.data.value as AIConfig[] | undefined) : undefined,
  )
  const channels = computed(() =>
    kind.value === 'channels' ? (query.data.value as ChannelConfig[] | undefined) : undefined,
  )
  async function remove(id: string) {
    const target = kind.value
    return action.run(async () => {
      await api.delete(target, id)
      await query.refresh()
    })
  }
  async function setEnabled(source: SourceConfig, enabled: boolean) {
    return action.run(async () => {
      await api.replace('sources', source.id, { ...source, enabled })
      await query.refresh()
    })
  }
  function sourceGateway(existing: boolean): SourceConfigEditorGateway {
    return {
      resolve: api.resolveSource,
      async save(target, value) {
        if (target.kind !== 'shared-resource') throw new Error('资源列表不能保存工作流草稿')
        if (existing) await api.replace('sources', target.resourceId, value)
        else await api.create('sources', value)
      },
    }
  }
  return {
    ...query,
    sources,
    providers,
    channels,
    action,
    remove,
    setEnabled,
    sourceGateway,
    protect: api.protectCredential,
  }
}
