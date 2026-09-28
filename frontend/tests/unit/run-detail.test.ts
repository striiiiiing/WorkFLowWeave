import { effectScope, isReadonly, nextTick, ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import {
  useRunDetail,
  usePhaseReport,
  type PhaseContent,
  type SessionRecord,
  type RunsApi,
  type PhaseIdentity,
} from '@/modules/runs/public'
const session = (id = 'one', version = 1): SessionRecord => ({
  session_id: id,
  workflow_id: 'daily',
  workflow_name: '每日',
  version,
  status: 'completed',
  stage: 'finish',
  created_at: '',
  updated_at: '',
  finished_at: '',
  error: null,
  artifacts: ['collect', 'analyze', 'aggregate', 'notify', 'finish'].map((stage) => ({
    stage: stage as SessionRecord['artifacts'][number]['stage'],
    content_version: version,
    availability: 'available' as const,
    size_bytes: null,
    error: null,
  })),
  snapshot_availability: 'available',
  execution_epoch: 'epoch-one',
  progress: [],
})
const phase = (id = 'one', version = 1): PhaseContent => ({
  session_id: id,
  version,
  stage: 'aggregate',
  content_version: version,
  availability: 'available',
  size_bytes: null,
  error: null,
  content: { outputs: { final: id } },
})
function api() {
  return {
    get: vi.fn().mockResolvedValue(session()),
    phase: vi.fn().mockResolvedValue(phase()),
    recovery: vi.fn().mockResolvedValue({ available: false, reason: null }),
    recover: vi.fn().mockResolvedValue({ session_id: 'new' }),
    cancel: vi.fn().mockResolvedValue({ session_id: 'one', cancelled: true }),
    trigger: vi.fn(),
  } satisfies Omit<RunsApi, 'list'>
}

describe('fixed report ownership', () => {
  it('rejects late reads across session, version and stage changes and after disposal', async () => {
    const pending: { signal: AbortSignal; finish: (p: PhaseContent) => void }[] = []
    const phaseApi = {
      phase: vi.fn(
        (_id, _stage, _version, signal) =>
          new Promise<PhaseContent>((finish) => pending.push({ signal, finish })),
      ),
    }
    const identity = ref<PhaseIdentity>({ id: 'one', version: 1, stage: 'aggregate' })
    const scope = effectScope()
    const report = scope.run(() => usePhaseReport(identity, phaseApi))!
    identity.value = { id: 'two', version: 2, stage: 'aggregate' }
    await nextTick()
    expect(pending[0].signal.aborted).toBe(true)
    pending[1].finish(phase('two', 2))
    await flushPromises()
    pending[0].finish(phase('one'))
    await flushPromises()
    expect(report.data.value?.session_id).toBe('two')
    identity.value = { id: 'two', version: 3, stage: 'aggregate' }
    await nextTick()
    expect(report.data.value).toBeUndefined()
    identity.value = { id: 'two', version: 3, stage: 'notify' }
    await nextTick()
    expect(pending[2].signal.aborted).toBe(true)
    expect(phaseApi.phase).toHaveBeenLastCalledWith('two', 'notify', 3, expect.any(AbortSignal))
    scope.stop()
    expect(pending[3].signal.aborted).toBe(true)
    pending[2].finish(phase('two', 3))
    await flushPromises()
    expect(report.data.value).toBeUndefined()
  })
  it('isolates phase failure, refreshes each identity once and exposes loaded context without another session read', async () => {
    const backend = api()
    backend.phase.mockImplementation(async (_id, stage, version) => {
      if (stage === 'notify') throw new Error('通知正文不可用')
      return { ...phase('one', version), stage }
    })
    const scope = effectScope()
    const detail = scope.run(() => useRunDetail(ref('one'), backend))!
    await flushPromises()
    expect(backend.get).toHaveBeenCalledTimes(1)
    expect(backend.phase).toHaveBeenCalledTimes(5)
    expect(detail.phases.notify.error.value).toBe('通知正文不可用')
    expect(detail.phases.aggregate.parsed.value?.result?.items[0].text).toBe('one')
    expect(detail.loadedContext.value?.session.version).toBe(1)
    expect(isReadonly(detail.loadedContext.value?.session)).toBe(true)
    expect(
      detail.loadedContext.value?.phases.find((phase) => phase.stage === 'aggregate')?.parsed
        ?.result?.items[0].text,
    ).toBe('one')
    await detail.refreshAll()
    await flushPromises()
    expect(backend.phase).toHaveBeenCalledTimes(10)
    expect(backend.recovery).toHaveBeenCalledTimes(2)
    backend.get.mockResolvedValue(session('one', 2))
    await detail.refreshAll()
    await flushPromises()
    expect(backend.phase).toHaveBeenCalledTimes(15)
    expect(backend.recovery).toHaveBeenCalledTimes(3)
    scope.stop()
  })
  it('does not navigate or refresh a new identity after an old recovery finishes', async () => {
    const backend = api()
    let finish!: (v: { session_id: string }) => void
    backend.recover.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve
      }),
    )
    const id = ref('one')
    const scope = effectScope()
    const detail = scope.run(() => useRunDetail(id, backend))!
    await flushPromises()
    const action = detail.recover()
    id.value = 'two'
    backend.get.mockResolvedValue(session('two'))
    await flushPromises()
    finish({ session_id: 'old-recovered' })
    expect(await action).toEqual({ status: 'busy' })
    expect(backend.get).toHaveBeenCalledTimes(2)
    scope.stop()
  })

  it('checks stage recovery only while enabled and preserves an explicit request ID', async () => {
    const backend = api()
    const scope = effectScope()
    const detail = scope.run(() => useRunDetail(ref('one'), backend))!
    await flushPromises()
    expect(backend.recovery).toHaveBeenCalledTimes(1)
    expect(backend.recovery).toHaveBeenCalledWith('one', {}, expect.any(AbortSignal))

    detail.stageRecoveryEnabled.value = true
    await flushPromises()
    expect(backend.recovery).toHaveBeenLastCalledWith(
      'one',
      { stage: 'collect' },
      expect.any(AbortSignal),
    )
    detail.selectedStage.value = 'notify'
    await flushPromises()
    expect(backend.recovery).toHaveBeenLastCalledWith(
      'one',
      { stage: 'notify' },
      expect.any(AbortSignal),
    )
    detail.stageRecoveryEnabled.value = false
    await flushPromises()
    expect(backend.recovery).toHaveBeenCalledTimes(3)

    await detail.resume({ stage: 'notify', checkpoint_id: 'checkpoint', request_id: 'stable' })
    expect(backend.recover).toHaveBeenCalledWith('one', {
      stage: 'notify',
      checkpoint_id: 'checkpoint',
      request_id: 'stable',
    })
    scope.stop()
  })
})
