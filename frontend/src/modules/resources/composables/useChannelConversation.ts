import { computed, ref, shallowRef, watch } from 'vue'
import { useAsyncTask, isTaskSuccess } from '@/shared/async/useAsyncTask'
import { useQuery } from '@/shared/async/useQuery'
import { useResourcesApi } from '../api/dependencies'
import type { ChannelConversation, ResourcesApi } from '../api/resourcesApi'

export function useChannelConversation(
  channelId: () => string,
  api: Pick<
    ResourcesApi,
    'channelConversation' | 'bindChannelConversation' | 'conversationOptions'
  > = useResourcesApi(),
) {
  const binding = shallowRef<ChannelConversation>()
  const selected = ref<string | null>(null)
  const action = useAsyncTask()
  const query = useQuery(
    async (signal) => {
      const [current, options] = await Promise.all([
        api.channelConversation(channelId(), signal),
        api.conversationOptions(signal),
      ])
      return { current, options }
    },
    [channelId],
  )
  watch(
    () => query.data.value,
    (data) => {
      binding.value = data?.current
      selected.value = data?.current.session_id ?? null
    },
  )

  async function save(sessionId: string | null = selected.value || null) {
    const id = channelId()
    const result = await action.run(() => api.bindChannelConversation(id, sessionId))
    if (isTaskSuccess(result) && channelId() === id) {
      binding.value = result.value
      selected.value = result.value.session_id
    }
    return result
  }

  return {
    binding,
    selected,
    options: computed(() => query.data.value?.options ?? []),
    query,
    action,
    save,
  }
}
