import { effectScope, nextTick, ref, shallowRef } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import {
  createFanIn,
  createWorkflow,
  sourceUsage,
  useWorkflowEditor,
} from '@/modules/workflows/public'
import type { WorkflowDefinition } from '@/modules/workflows/public'
import type { SourceConfigEditorGateway } from '@/modules/resources/public'

function setup(initial: WorkflowDefinition, id = initial.id) {
  const identity = ref<string | undefined>(id)
  const data = shallowRef<WorkflowDefinition | undefined>(initial)
  const scope = effectScope()
  const editor = scope.run(() => useWorkflowEditor({ identity, data }))!
  return { identity, data, editor, scope }
}

describe('workflow model and editor', () => {
  it('starts with shared prompts and inheriting analysis and fan-in prompts', () => {
    const workflow = createWorkflow()
    expect(workflow.system_prompt).toBe('')
    expect(workflow.input_prompt).toBe('{input}')
    const { editor, scope } = setup(workflow)
    editor.addTask()
    expect(editor.createFanIn().reuse_from).toBe('$first')
    editor.toggleFanIn(true)
    expect(editor.draft.value?.analyses[0]).toMatchObject({
      system_prompt: null,
      input_prompt: null,
      user_prompt: '',
    })
    expect(editor.draft.value?.fan_in).toMatchObject({
      system_prompt: null,
      input_prompt: null,
      user_prompt: '',
      reuse_from: '$first',
    })
    scope.stop()
  })

  it('does not select a missing first task and clears it when the last task is deleted', () => {
    const { editor, scope } = setup(createWorkflow())
    expect(editor.createFanIn().reuse_from).toBeNull()
    editor.toggleFanIn(true)
    expect(editor.draft.value?.fan_in?.reuse_from).toBeNull()
    editor.toggleFanIn(false)
    editor.addTask()
    editor.toggleFanIn(true)
    expect(editor.draft.value?.fan_in?.reuse_from).toBeNull()
    editor.toggleFanIn(false)
    editor.toggleFanIn(true)
    editor.updateFanIn({ reuse_from: '$first' })
    editor.deleteTask(0)
    expect(editor.draft.value?.fan_in?.reuse_from).toBeNull()
    scope.stop()
  })

  it('preserves an existing explicit first-task model source', () => {
    const workflow = {
      ...createWorkflow(),
      fan_in: { ...createFanIn(), reuse_from: '$first' },
    }
    const { editor, scope } = setup(workflow)
    expect(editor.draft.value?.fan_in?.reuse_from).toBe('$first')
    editor.toggleFanIn(false)
    editor.toggleFanIn(true)
    expect(editor.draft.value?.fan_in?.reuse_from).toBe('$first')
    scope.stop()
  })

  it('keeps a single immutable draft through nested actions', () => {
    const initial = {
      ...createWorkflow(),
      id: 'workflow',
      analyses: [
        {
          id: 'first',
          ai: '',
          model: '',
          system_prompt: null,
          input_prompt: null,
          user_prompt: '',
        },
        {
          id: 'second',
          ai: '',
          model: '',
          system_prompt: null,
          input_prompt: null,
          user_prompt: '',
        },
      ],
      fan_in: { ...createFanIn(), order: ['first', 'second'] },
    }
    const { editor, scope } = setup(initial)
    const before = editor.draft.value!
    expect(editor.updateTaskId(0, 'second')).toContain('不能重名')
    expect(editor.draft.value).toBe(before)
    expect(editor.updateTaskId(0, 'renamed')).toBe('')
    expect(editor.draft.value).not.toBe(before)
    expect(editor.draft.value?.fan_in?.order).toEqual(['renamed', 'second'])
    const draft = editor.draft.value!
    editor.toggleFanIn(false)
    expect(editor.draft.value?.fan_in).toBeNull()
    editor.toggleFanIn(true)
    expect(editor.draft.value?.fan_in).toEqual(draft.fan_in)
    scope.stop()
  })

  it('accepts server data only when the route identity changes', async () => {
    const first = { ...createWorkflow(), id: 'first', name: 'server first' }
    const second = { ...createWorkflow(), id: 'second', name: 'server second' }
    const { identity, data, editor, scope } = setup(first)
    editor.update({ name: 'unsaved' })
    data.value = { ...first, name: 'late refresh' }
    await nextTick()
    expect(editor.draft.value?.name).toBe('unsaved')
    identity.value = 'second'
    await nextTick()
    data.value = first
    await nextTick()
    expect(editor.draft.value).toBeUndefined()
    data.value = second
    await nextTick()
    expect(editor.draft.value).toMatchObject({ id: 'second', name: 'server second' })
    scope.stop()
  })

  it('updates fan-in references when tasks change, including a disabled fan-in draft', () => {
    const initial = {
      ...createWorkflow(),
      id: 'workflow',
      analyses: [
        {
          id: 'first',
          ai: 'ai',
          model: 'one',
          system_prompt: null,
          input_prompt: null,
          user_prompt: '',
        },
        {
          id: 'second',
          ai: 'ai',
          model: 'two',
          system_prompt: null,
          input_prompt: null,
          user_prompt: '',
        },
      ],
      fan_in: { ...createFanIn(), order: ['$input', 'second', 'first'], reuse_from: 'second' },
    }
    const { editor, scope } = setup(initial)
    editor.updateTaskId(1, 'renamed')
    expect(editor.draft.value?.fan_in).toMatchObject({
      order: ['$input', 'renamed', 'first'],
      reuse_from: 'renamed',
    })
    editor.toggleFanIn(false)
    editor.updateTaskId(1, 'final')
    editor.deleteTask(1)
    editor.toggleFanIn(true)
    expect(editor.draft.value?.fan_in).toMatchObject({
      order: ['$input', 'first'],
      reuse_from: '$first',
    })
    scope.stop()
  })

  it('detaches and publishes source values through the injected gateway', async () => {
    const workflow = { ...createWorkflow(), id: 'workflow', sources: ['logs'] }
    const { editor, scope } = setup(workflow)
    const source = {
      id: 'logs',
      collector: 'mock',
      enabled: true,
      options: { limit: 3 },
      setters: {},
      template: null,
      timeout: 60,
      on_error: 'stop' as const,
      on_missing: 'stop' as const,
      on_empty: 'stop' as const,
      on_filtered_empty: 'stop' as const,
    }
    const gateway: SourceConfigEditorGateway = {
      resolve: vi.fn().mockResolvedValue(source),
      save: vi.fn().mockResolvedValue(undefined),
    }
    await editor.detachSource('logs', gateway)
    expect(editor.draft.value?.source_overrides.logs.source).toEqual(source)
    await editor.publishSource('logs', gateway, true)
    expect(gateway.save).toHaveBeenCalledWith(
      { kind: 'shared-resource', resourceId: 'logs' },
      source,
    )
    expect(editor.draft.value?.source_overrides).toEqual({})
    scope.stop()
  })

  it('rejects a late source resolution after the workflow identity changes', async () => {
    const first = { ...createWorkflow(), id: 'first', sources: ['logs'] }
    const { editor, identity, data, scope } = setup(first)
    let finish!: (value: Awaited<ReturnType<SourceConfigEditorGateway['resolve']>>) => void
    const gateway: SourceConfigEditorGateway = {
      resolve: vi.fn(() => new Promise((resolve) => (finish = resolve))),
      save: vi.fn(),
    }
    const pending = editor.detachSource('logs', gateway)
    identity.value = 'second'
    await nextTick()
    data.value = { ...createWorkflow(), id: 'second', sources: ['other'] }
    await nextTick()
    finish({ id: 'logs' } as Awaited<ReturnType<SourceConfigEditorGateway['resolve']>>)
    expect(await pending).toMatchObject({ status: 'error' })
    expect(editor.draft.value?.source_overrides).toEqual({})
    expect(editor.draft.value?.id).toBe('second')
    scope.stop()
  })

  it('projects detached source usage without importing resource state', () => {
    const shared = { ...createWorkflow(), id: 'shared', sources: ['logs'] }
    const detached = {
      ...createWorkflow(),
      id: 'detached',
      sources: ['logs'],
      source_overrides: { logs: { source: { id: 'logs' } } },
    }
    expect(sourceUsage('logs', [shared, detached])).toEqual([
      { id: 'shared', name: 'shared', detached: false },
      { id: 'detached', name: 'detached', detached: true },
    ])
  })
})
