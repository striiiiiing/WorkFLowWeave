import { defineComponent, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElPopconfirm } from 'element-plus'
import { afterEach, expect, it, vi } from 'vitest'
import { resourcesApi } from '@/app/services'
import SourceStepCard from '@/modules/workflows/ui/SourceStepCard.vue'
import { SourceSummary, SourceEditorSession } from '@/modules/resources/public'
import { createResource, resourceKinds } from '@/modules/resources/public'
import { createWorkflow, sourceUsage, useWorkflowEditor } from '@/modules/workflows/public'
import type { SourceConfig, WorkflowDefinition } from '@/shared/types'

vi.mock('@/app/services', () => ({
  resourcesApi: { resolveSource: vi.fn(), replace: vi.fn() },
}))
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.clearAllMocks()
})

function setup() {
  const source = {
    ...createResource('sources'),
    id: 'logs',
    collector: 'mock',
    options: { limit: 3 },
  } as SourceConfig
  const initial: WorkflowDefinition = {
    ...createWorkflow(),
    id: 'current',
    sources: ['logs'],
  }
  const peer = { ...createWorkflow(), id: 'peer', sources: ['logs'] }
  const sources = ref([source])
  let editor!: ReturnType<typeof useWorkflowEditor>
  const wrapper = mount(
    defineComponent({
      components: { SourceStepCard },
      setup: () => {
        editor = useWorkflowEditor({ identity: undefined })
        editor.replace(initial)
        return {
          editor,
          sources,
          usage: (id: string) => sourceUsage(id, [editor.draft.value!, peer]),
          gateway: { resolve: resourcesApi.resolveSource, save: vi.fn() },
          protect: vi.fn(),
        }
      },
      template:
        '<el-form :model="editor.draft"><SourceStepCard :editor="editor" :sources="sources" :usage="usage" :gateway="gateway" :capabilities="[]" :protect="protect" /></el-form>',
    }),
    { global: { plugins: [ElementPlus], stubs: { SourceEditorSession: true } } },
  )
  wrappers.push(wrapper)
  const button = (text: string) => wrapper.findAll('button').find((item) => item.text() === text)!
  return { wrapper, source, workflow: editor.draft, editor, sources, peer, button }
}

it('requires detaching a shared source and retains the independent configuration when the center changes', async () => {
  const { wrapper, source, workflow, sources, button } = setup()
  expect(button('编辑配置').attributes('disabled')).toBeDefined()
  expect(wrapper.text()).toContain('全局同步 (2)')
  vi.mocked(resourcesApi.resolveSource).mockResolvedValue(structuredClone(source))
  await button('脱离共用配置').trigger('click')
  await flushPromises()
  expect(resourcesApi.resolveSource).toHaveBeenCalledWith('logs', undefined)
  sources.value = [{ ...source, options: { limit: 99 } }]
  await flushPromises()
  expect(wrapper.getComponent(SourceSummary).props('source').options).toEqual({ limit: 3 })
  expect(workflow.value.source_overrides.logs.source?.options).toEqual({ limit: 3 })
  expect(resourcesApi.replace).not.toHaveBeenCalled()

  await button('编辑配置').trigger('click')
  const sourceEditor = wrapper.getComponent(SourceEditorSession)
  sourceEditor.vm.$emit('saved', { ...source, options: { limit: 8 } })
  await flushPromises()
  expect(workflow.value.source_overrides.logs.source?.options).toEqual({ limit: 8 })
  expect(sources.value[0].options).toEqual({ limit: 99 })

  wrapper.getComponent(ElPopconfirm).vm.$emit('confirm', new MouseEvent('click'))
  await flushPromises()
  expect(workflow.value.source_overrides).toEqual({})
  expect(wrapper.getComponent(SourceSummary).props('source').options).toEqual({ limit: 99 })
})

it('surfaces resolution failure and keeps the original binding intact', async () => {
  const { wrapper, workflow, button } = setup()
  vi.mocked(resourcesApi.resolveSource).mockRejectedValue(new Error('来源无法解析'))
  await button('脱离共用配置').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('来源无法解析')
  expect(workflow.value.source_overrides).toEqual({})
  expect(wrapper.text()).toContain('全局同步 (2)')
})

it('requires explicit detachment before editing a legacy sparse override', async () => {
  const { wrapper, workflow, button } = setup()
  const editor = wrapper.getComponent(SourceStepCard).props('editor')
  editor.setSource('logs', { options: { limit: 5 }, setters: {}, template: null })
  await flushPromises()
  expect(button('编辑配置').attributes('disabled')).toBeDefined()
  expect(wrapper.text()).toContain('多个工作流共用此数据源')
  expect(workflow.value.source_overrides.logs.source).toBeUndefined()
  expect(resourcesApi.resolveSource).not.toHaveBeenCalled()
})

it('adds the persisted source to the workflow without replacing other bindings', async () => {
  const { wrapper, workflow, source, button } = setup()
  await button('新增采集源').trigger('click')
  const added = { ...source, id: 'new-source' }
  wrapper.getComponent(SourceEditorSession).vm.$emit('saved', added)
  await flushPromises()
  expect(workflow.value.sources).toEqual(['logs', 'new-source'])
})

it('counts sparse legacy overrides as shared and complete snapshots as independent', () => {
  const shared = {
    ...createWorkflow(),
    id: 'shared',
    sources: ['logs'],
    source_overrides: { logs: { options: { limit: 5 }, setters: {}, template: null } },
  }
  const source = { ...createResource('sources'), id: 'logs', collector: 'mock' } as SourceConfig
  const independent = {
    ...shared,
    id: 'independent',
    source_overrides: { logs: { ...shared.source_overrides.logs, source } },
  }
  expect(sourceUsage('logs', [shared, independent]).map((item) => item.detached)).toEqual([
    false,
    true,
  ])
  expect(resourceKinds.map((kind) => kind.key)).toEqual([
    'sources',
    'mcp_servers',
    'ai',
    'channels',
  ])
})
