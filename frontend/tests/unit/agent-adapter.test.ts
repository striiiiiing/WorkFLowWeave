import { describe, expect, it, vi } from 'vitest'
import { AgentServerAdapter } from '@/modules/agents/langchain/adapter'
import type { AgentsApi } from '@/modules/agents/api/agentsApi'
import type { AgentEvent, AgentSession } from '@/modules/agents/model/public'

const session = (id: string): AgentSession =>
  ({ session_id: id, status: 'completed', turn_id: 'turn-2' }) as AgentSession

const event = (
  id: number,
  sessionId: string,
  turnId: string | null,
  type: string,
  data: Record<string, unknown> = {},
): AgentEvent => ({
  id,
  session_id: sessionId,
  turn_id: turnId,
  type,
  at: '2026-10-06T00:00:00Z',
  data,
})

const history = [
  event(1, 's', 'turn-1', 'message.user', { message_id: 'user-1', text: 'first question' }),
  event(2, 's', 'turn-1', 'message.completed', {
    message_id: 'assistant-1',
    incremental: false,
    text: 'first answer',
  }),
  event(3, 's', 'turn-1', 'turn.completed', { checkpoint_id: 'checkpoint-1' }),
  event(4, 's', 'turn-2', 'message.user', { message_id: 'user-2', text: 'second question' }),
  event(5, 's', 'turn-2', 'message.completed', {
    message_id: 'assistant-2',
    incremental: false,
    text: 'second answer',
  }),
  event(6, 's', 'turn-2', 'turn.completed', { checkpoint_id: 'checkpoint-2' }),
]

function messageText(content: unknown): string {
  if (typeof content === 'string') return content
  if (!Array.isArray(content)) return ''
  return content
    .map((part) =>
      part && typeof part === 'object' && 'text' in part && typeof part.text === 'string'
        ? part.text
        : '',
    )
    .join('')
}

function makeApi(overrides: Partial<AgentsApi> = {}) {
  return {
    history: vi.fn(async () => history),
    get: vi.fn(async () => session('s')),
    fork: vi.fn(async (id: string) => session(`${id}-fork`)),
    ...overrides,
  } as unknown as AgentsApi
}

describe('AgentServerAdapter', () => {
  it('returns the checkpointed state and a distinct message snapshot for each history entry', async () => {
    const adapter = new AgentServerAdapter(makeApi())
    adapter.setThreadId('s')
    adapter.seedSession(session('s'), history)

    const current = await adapter.getState<{ messages: Array<{ content: string }> }>()
    expect(current?.next).toEqual([])
    expect(current?.checkpoint).toEqual({ checkpoint_id: 'checkpoint-2' })
    expect(current?.values.messages.map((message) => messageText(message.content))).toEqual([
      'first question',
      'first answer',
      'second question',
      'second answer',
    ])
    const stateCommand = {
      id: 'state-1',
      method: 'state.get',
      params: {},
    } as Parameters<AgentServerAdapter['send']>[0]
    await expect(adapter.send(stateCommand)).resolves.toMatchObject({
      type: 'success',
      id: 'state-1',
      result: { checkpoint: { checkpoint_id: 'checkpoint-2' }, next: [] },
    })

    const checkpoints = await adapter.getHistory<{ messages: Array<{ content: string }> }>({
      limit: 2,
    })
    expect(checkpoints.map((item) => item.checkpoint?.checkpoint_id)).toEqual([
      'checkpoint-2',
      'checkpoint-1',
    ])
    expect(checkpoints[0].values.messages).toHaveLength(4)
    expect(checkpoints[1].values.messages.map((message) => messageText(message.content))).toEqual([
      'first question',
      'first answer',
    ])

    const latestOnly = await adapter.getHistory({ limit: 1 })
    expect(latestOnly.map((item) => item.checkpoint?.checkpoint_id)).toEqual(['checkpoint-2'])
  })

  it('forks an inherited checkpoint from the session that owns its event', async () => {
    const api = makeApi({
      history: vi.fn(async () => [
        event(1, 'parent', 'parent-turn', 'turn.completed', { checkpoint_id: 'parent-cp' }),
        event(1, 'child', 'child-turn', 'turn.completed', { checkpoint_id: 'child-cp' }),
      ]),
    })
    const adapter = new AgentServerAdapter(api)
    adapter.setThreadId('child')
    adapter.seedSession(session('child'), [
      event(1, 'parent', 'parent-turn', 'turn.completed', { checkpoint_id: 'parent-cp' }),
    ])
    const forkCommand = {
      id: 'fork-1',
      method: 'state.fork',
      params: { checkpoint_id: 'parent-cp' },
    } as Parameters<AgentServerAdapter['send']>[0]

    await adapter.send(forkCommand)
    expect(api.fork).toHaveBeenCalledWith('parent', { turn_id: 'parent-turn' })
    await adapter.fork('parent', { turn_id: 'parent-turn' })
    expect(api.fork).toHaveBeenCalledTimes(2)
  })

  it('keeps connection state connected while another subscription rotates out', async () => {
    class Source {
      onopen?: () => void
      onmessage?: (message: MessageEvent<string>) => void
      onerror?: () => void
      closed = false
      close() {
        this.closed = true
      }
    }
    const sources: Source[] = []
    const states: string[] = []
    const adapter = new AgentServerAdapter(makeApi(), {
      sourceFactory: () => {
        const source = new Source()
        sources.push(source)
        return source
      },
      onConnectionState: (state) => states.push(state),
    })
    adapter.setThreadId('s')
    const params = { channels: ['custom:agent'] } as Parameters<
      NonNullable<AgentServerAdapter['openEventStream']>
    >[0]
    const first = adapter.openEventStream(params)
    const second = adapter.openEventStream(params)
    sources[0].onopen?.()
    sources[1].onopen?.()
    first.close()
    expect(states.at(-1)).toBe('connected')
    second.close()
    expect(states.at(-1)).toBe('closed')
    expect(states).toEqual(['loading', 'connected', 'closed'])
  })

  it('preserves queued SSE events beyond the former silent truncation threshold', async () => {
    class Source {
      onopen?: () => void
      onmessage?: (message: MessageEvent<string>) => void
      onerror?: () => void
      close() {}
    }
    let source!: Source
    const adapter = new AgentServerAdapter(makeApi(), {
      sourceFactory: () => (source = new Source()),
    })
    adapter.setThreadId('s')
    const params = { channels: ['custom:agent'] } as Parameters<
      NonNullable<AgentServerAdapter['openEventStream']>
    >[0]
    const stream = adapter.openEventStream(params)
    source.onopen?.()
    await stream.ready

    const total = 10005
    for (let id = 1; id <= total; id++) {
      source.onmessage?.({
        data: JSON.stringify(event(id, 's', 'turn', 'future.event')),
      } as MessageEvent<string>)
    }

    const reader = stream.events[Symbol.asyncIterator]()
    let received = 0
    for (; received < total; received++) expect((await reader.next()).done).toBe(false)
    stream.close()
    expect(received).toBe(total)
  }, 10000)
})
