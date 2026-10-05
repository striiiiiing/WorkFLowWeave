import { describe, expect, it } from 'vitest'
import { parseAgentEvent } from '@/modules/agents/model/events'
import { projectAgentSession } from '@/modules/agents/model/sessionProjection'
import type { AgentEvent, AgentSession } from '@/modules/agents/model/types'

const session = (status = 'running', turnId = 'current'): AgentSession => ({
  session_id: 's',
  branch_id: 'main',
  model: null,
  workflow_session_id: null,
  created_at: '2026-09-23',
  updated_at: '2026-09-23',
  status,
  turn_id: turnId,
  context_budget: null,
  continuable: true,
  history_path: '',
  last_checkpoint_at: null,
})
const event = (
  id: number,
  type: string,
  turnId = 'current',
  data: Record<string, unknown> = {},
): AgentEvent => ({
  id,
  session_id: 's',
  turn_id: turnId,
  type,
  at: '2026-09-23',
  data,
})

describe('Agent event model', () => {
  it('updates a topic title independently of the active turn', () => {
    const renamed = {
      ...event(1, 'session.title.changed', 'old', { title: '告警复盘' }),
      turn_id: null,
    }
    expect(projectAgentSession(session(), parseAgentEvent(renamed))).toMatchObject({
      title: '告警复盘',
      status: 'running',
      turn_id: 'current',
    })
  })

  it('accepts reasoning-only provider deltas and rejects a malformed reasoning payload', () => {
    expect(
      parseAgentEvent(event(1, 'message.delta', 'current', { reasoning: '实际思考' })).data,
    ).toEqual({ reasoning: '实际思考' })
    expect(() => parseAgentEvent(event(2, 'message.delta', 'current', { reasoning: 42 }))).toThrow(
      'message.delta',
    )
  })

  it('retains unknown events and rejects malformed known payloads', () => {
    expect(parseAgentEvent(event(1, 'future.detail', 'current', { extra: 1 }))).toEqual(
      event(1, 'future.detail', 'current', { extra: 1 }),
    )
    expect(() =>
      parseAgentEvent(event(2, 'message.completed', 'current', { text: 'reply' })),
    ).toThrow('message.completed')
    expect(() =>
      parseAgentEvent(event(4, 'context.budget', 'current', { total: 10, remaining: 4 })),
    ).toThrow('context.budget')
    expect(() => parseAgentEvent({ ...event(3, 'turn.completed'), id: 0 })).toThrow('信封无效')
  })

  it('projects only the active turn while allowing its successor after completion', () => {
    const current = session()
    expect(projectAgentSession(current, event(1, 'turn.completed', 'old'))).toBe(current)
    expect(projectAgentSession(current, event(2, 'turn.started', 'old'))).toBe(current)
    const completed = projectAgentSession(
      current,
      event(3, 'turn.completed', 'current', {
        checkpoint_id: 'checkpoint',
      }),
    )
    expect(completed).toMatchObject({ status: 'completed', last_checkpoint_at: '2026-09-23' })
    expect(projectAgentSession(completed, event(4, 'turn.started', 'next'))).toMatchObject({
      status: 'running',
      turn_id: 'next',
    })
  })

  it('projects budget, resources and checkpoint failure without changing the source', () => {
    const current = session()
    const budget = {
      total: 10,
      remaining: 4,
      messages: 3,
      system: 1,
      tools: 1,
      output: 1,
      window: 10,
      estimated: true,
      token_counter: 'test',
    }
    const updated = projectAgentSession(
      current,
      parseAgentEvent(event(1, 'context.budget', 'current', budget)),
    )
    const resources = projectAgentSession(
      updated,
      parseAgentEvent(
        event(2, 'turn.resources', 'current', {
          model: 'provider:model',
          tools_generation: 2,
        }),
      ),
    )
    const failed = projectAgentSession(
      resources,
      event(3, 'turn.failed', 'current', {
        error: { code: 'checkpoint_missing', message: 'missing' },
      }),
    )
    expect(current.context_budget).toBeNull()
    expect(failed).toMatchObject({
      status: 'failed',
      context_budget: budget,
      active_resources: { model: 'provider:model', tools_generation: 2 },
      continuable: false,
      continuation_error: { code: 'checkpoint_missing', message: 'missing' },
    })
  })
})
