import { vi } from 'vitest'
import type { RunEventHandlers, SessionRecord, WorkflowProgress } from '@/modules/runs/public'

export function progress(overrides: Partial<WorkflowProgress> = {}): WorkflowProgress {
  return {
    session_id: 'one',
    execution_epoch: 'epoch-one',
    stage: 'collect',
    event: 'item',
    status: 'pending',
    item_id: 'fast',
    output_id: null,
    channel_id: null,
    label: '快速来源',
    result_ref: null,
    version: null,
    availability: 'pending',
    error: null,
    summary: {},
    ...overrides,
  }
}

export function session(overrides: Partial<SessionRecord> = {}): SessionRecord {
  return {
    session_id: 'one',
    workflow_id: 'daily',
    workflow_name: '每日汇总',
    version: 1,
    status: 'running',
    stage: 'collect',
    created_at: '2026-09-28T01:00:00Z',
    updated_at: '2026-09-28T01:00:00Z',
    finished_at: null,
    error: null,
    artifacts: [],
    snapshot_availability: 'available',
    execution_epoch: 'epoch-one',
    progress: [progress(), progress({ item_id: 'slow', label: '慢速来源' })],
    ...overrides,
  }
}

export function runStream() {
  const connections: { id: string; handlers: RunEventHandlers; close: ReturnType<typeof vi.fn> }[] =
    []
  const subscribe = vi.fn((id: string, handlers: RunEventHandlers) => {
    const close = vi.fn()
    connections.push({ id, handlers, close })
    return close
  })
  return { subscribe, connections }
}

export function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (cause: unknown) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}
