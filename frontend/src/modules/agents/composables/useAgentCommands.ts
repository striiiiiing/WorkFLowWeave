import { computed, reactive, ref } from 'vue'
import { ApiError } from '@/shared/api/errors'
import { useErrorFormatter } from '@/shared/async/errorFormatter'
import type { AgentsApi } from '../api/agentsApi'
import type { TurnAccepted } from '../model/public'

type CommandResult = Awaited<ReturnType<AgentsApi['command']>>

interface PendingInput {
  session: string | null
  draft: string
  text: string
  requestId: string
  model?: string
}

interface InputState {
  draft: string
  pendingInput?: PendingInput
  pending: boolean
  stopPending: boolean
  uncertain: boolean
  retrySafe: boolean
  error: string
  stopError: string
}

const unsafeRetry = /^\/(?:workflow\s+\S|(?:new|fork|compact)(?:\s|$))/

interface AgentStreamCommands {
  submit?: (
    sessionId: string,
    text: string,
    requestId: string,
    append: boolean,
  ) => Promise<TurnAccepted>
  cancel?: (sessionId: string) => Promise<Awaited<ReturnType<AgentsApi['cancel']>>>
}

export function useAgentCommands(
  api: Pick<AgentsApi, 'command' | 'cancel'>,
  streamCommands: AgentStreamCommands = {},
) {
  const formatError = useErrorFormatter()
  const states = reactive<Record<string, InputState>>(commandStateStore)
  const selectedId = ref<string | null>(null)

  function stateFor(id: string | null): InputState {
    const key = id ?? ''
    return (states[key] ??= {
      draft: '',
      pending: false,
      stopPending: false,
      uncertain: false,
      retrySafe: true,
      error: '',
      stopError: '',
    })
  }

  const current = computed(() => stateFor(selectedId.value))
  const draft = computed({
    get: () => current.value.draft,
    set: (text: string) => {
      const state = current.value
      state.draft = text
      if (state.pendingInput && text !== state.pendingInput.draft) {
        state.pendingInput = undefined
        state.uncertain = false
        state.retrySafe = true
      }
    },
  })

  function select(id: string | null) {
    selectedId.value = id
  }

  function clear() {
    for (const key of Object.keys(states)) delete states[key]
    selectedId.value = null
  }

  async function send(running: boolean, model?: string): Promise<CommandResult | undefined> {
    const id = selectedId.value
    const state = stateFor(id)
    const originalDraft = state.draft
    if (!originalDraft.trim() || state.pending || (state.uncertain && !state.retrySafe)) return
    const text =
      running && !originalDraft.trim().startsWith('/') ? `/append ${originalDraft}` : originalDraft
    if (!state.pendingInput || state.pendingInput.draft !== originalDraft) {
      state.pendingInput = {
        session: id,
        draft: originalDraft,
        text,
        requestId: crypto.randomUUID(),
        model,
      }
      state.retrySafe = !unsafeRetry.test(text.trim())
      state.uncertain = false
    }
    const input = state.pendingInput
    state.pending = true
    state.error = ''
    try {
      const result =
        !input.text.trim().startsWith('/') && streamCommands.submit
          ? {
              kind: 'turn' as const,
              priority: running ? 'command' : 'conversation',
              result: await streamCommands.submit(
                input.session ?? '',
                input.text,
                input.requestId,
                running,
              ),
            }
          : await api.command(input.session, input.text, input.requestId, input.model)
      if (state.pendingInput === input) {
        state.pendingInput = undefined
        state.uncertain = false
        if (state.draft === input.draft) state.draft = ''
      }
      return result
    } catch (cause) {
      if (state.pendingInput === input) {
        state.uncertain = !(cause instanceof ApiError) || cause.status >= 500
        if (!state.uncertain) state.pendingInput = undefined
        state.error = formatError(cause)
      }
    } finally {
      state.pending = false
    }
  }

  async function stop(): Promise<Awaited<ReturnType<AgentsApi['cancel']>> | undefined> {
    const id = selectedId.value
    if (!id) return
    const state = stateFor(id)
    if (state.stopPending) return
    state.stopPending = true
    state.stopError = ''
    try {
      return await (streamCommands.cancel ?? api.cancel)(id)
    } catch (cause) {
      state.stopError = formatError(cause)
    } finally {
      state.stopPending = false
    }
  }

  return { current, draft, select, send, stop, stateFor, clear }
}

const commandStateStore: Record<string, InputState> = {}
