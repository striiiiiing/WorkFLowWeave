import { ref } from 'vue'
import { isTaskSuccess, useAsyncTask } from '@/shared/async/useAsyncTask'
import type { AgentsApi } from '../api/agentsApi'
import type { AgentEvent, AgentSession } from '../model/public'

export function useAgentBranches(api: Pick<AgentsApi, 'fork' | 'send'>) {
  const action = useAsyncTask()
  const event = ref<AgentEvent>()
  const draft = ref('')
  const branch = ref<AgentSession>()
  const requestId = ref('')

  function start(selected: AgentEvent) {
    event.value = selected
    draft.value = String(selected.data.text ?? '')
    branch.value = undefined
    requestId.value = crypto.randomUUID()
    action.error.value = ''
  }

  function close() {
    if (!action.pending.value) event.value = undefined
  }

  async function confirm(): Promise<AgentSession | undefined> {
    const origin = event.value
    const text = draft.value
    if (!origin || !text.trim()) return
    const result = await action.run(async () => {
      const child =
        branch.value ??
        (await api.fork(origin.session_id, {
          message_id: String(origin.data.message_id),
        }))
      branch.value = child
      await api.send(child.session_id, requestId.value, text)
      return child
    })
    if (!isTaskSuccess(result)) return
    event.value = undefined
    return result.value
  }

  return { action, event, draft, branch, start, close, confirm }
}
