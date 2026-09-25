import { createWorkflow } from '@/domain/workflow'
import { computed, defineComponent, effectScope, ref } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { useResourceList } from '@/modules/resources/composables/useResourceList'
import { useSourceEditor } from '@/modules/resources/composables/useSourceEditor'
import { createResource } from '@/modules/resources/model/resources'
import { useSourceUsage } from '@/pages/integrations/useSourceUsage'
import { workflowsApiKey } from '@/modules/workflows/public'
import type { SourceConfig } from '@/modules/resources/model/types'
import type { ResourcesApi } from '@/modules/resources/api/resourcesApi'

const source = {
  ...createResource('sources'),
  id: 's',
  collector: 'mock',
  enabled: false,
} as SourceConfig

describe('resource query and editor ownership', () => {
  it('refreshes the catalog without replacing the open editor or re-resolving its source', async () => {
    const api = {
      list: vi.fn().mockResolvedValue([source]),
      resolveSource: vi.fn().mockResolvedValue(source),
      replace: vi.fn().mockResolvedValue(source),
    } as unknown as ResourcesApi
    const scope = effectScope()
    const { list, editor } = scope.run(() => {
      const list = useResourceList(ref('sources'), api)
      return {
        list,
        editor: useSourceEditor(
          { initial: source, target: { kind: 'shared-resource', resourceId: 's' } },
          list.sourceGateway(true),
        ),
      }
    })!
    await flushPromises()
    editor.updateBasic({ display_name: 'unsaved draft' })
    vi.mocked(api.list).mockResolvedValue([{ ...source, display_name: 'server replacement' }])
    await list.refresh()
    expect(list.sources.value?.[0].display_name).toBe('server replacement')
    expect(editor.value.value?.display_name).toBe('unsaved draft')
    expect(editor.value.value?.enabled).toBe(false)
    expect(api.resolveSource).toHaveBeenCalledTimes(1)
    scope.stop()
  })

  it('refuses a workflow target in the shared resource gateway before any PUT', async () => {
    const api = { list: vi.fn().mockResolvedValue([]), replace: vi.fn() } as unknown as ResourcesApi
    const scope = effectScope()
    const list = scope.run(() => useResourceList(ref('sources'), api))!
    await expect(
      list
        .sourceGateway(true)
        .save({ kind: 'workflow-draft', workflowId: 'w', sourceId: 's' }, source),
    ).rejects.toThrow('不能保存工作流草稿')
    expect(api.replace).not.toHaveBeenCalled()
    scope.stop()
  })

  it('marks usages unknown on failed refresh despite a retained successful snapshot', async () => {
    const list = vi
      .fn()
      .mockResolvedValue([{ id: 'w', name: '工作流', sources: ['s'], source_overrides: {} }])
    let usage!: ReturnType<typeof useSourceUsage>
    const wrapper = mount(
      defineComponent({
        setup() {
          usage = useSourceUsage()
          const references = computed(() => usage.references('s'))
          return { references }
        },
        template: '<div>{{ references === undefined ? "unknown" : references.length }}</div>',
      }),
      {
        global: { provide: { [workflowsApiKey as symbol]: { list } } },
      },
    )
    await flushPromises()
    expect(wrapper.text()).toBe('1')
    list.mockRejectedValue(new Error('offline'))
    await usage.refresh()
    expect(usage.data.value).toHaveLength(1)
    expect(wrapper.text()).toBe('unknown')
    expect(usage.error.value).toContain('offline')
    wrapper.unmount()
  })
})

it('replaces the current server workflow with its draft exactly once for usage projection', async () => {
  const stored = { ...createWorkflow(), id: 'current', sources: ['s'] }
  const draft = ref({
    ...stored,
    source_overrides: { s: { source, options: {}, setters: {}, template: null } },
  })
  const list = vi.fn().mockResolvedValue([stored, { ...stored, id: 'peer' }])
  let usage!: ReturnType<typeof useSourceUsage>
  const wrapper = mount(
    defineComponent({
      setup() {
        usage = useSourceUsage({ currentDraft: () => draft.value })
        return () => null
      },
    }),
    { global: { provide: { [workflowsApiKey as symbol]: { list } } } },
  )
  await flushPromises()
  expect(usage.references('s')).toEqual([
    { id: 'peer', name: 'peer', detached: false },
    { id: 'current', name: 'current', detached: true },
  ])
  expect(list).toHaveBeenCalledTimes(1)
  draft.value = { ...draft.value, sources: [] }
  expect(usage.references('s')).toEqual([{ id: 'peer', name: 'peer', detached: false }])
  wrapper.unmount()
})
