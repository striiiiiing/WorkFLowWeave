import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ResourcesView from '@/pages/resources/ResourcesPage.vue'
import { resourcesApiKey, createResource, type SourceConfig } from '@/modules/resources/public'
import { workflowsApiKey } from '@/modules/workflows/public'
import { systemApiKey } from '@/modules/system/public'
import SourceList from '@/modules/resources/ui/SourceList.vue'
import SourceConfigEditor from '@/modules/resources/ui/SourceConfigEditor.vue'
import { resourcesApi } from '@/api/resources'

vi.mock('@/api/resources', () => ({
  resourcesApi: {
    list: vi.fn(),
    resolveSource: vi.fn(),
    delete: vi.fn(),
    create: vi.fn(),
    replace: vi.fn(),
    protectCredential: vi.fn(),
    checkAIConnection: vi.fn(),
  },
}))

const provider = {
  id: 'provider',
  provider: 'http',
  base_url: 'https://example.test/v1',
  api_key: null,
  system_prompt: '',
  models: { 'vendor.model/pro': {}, 'vendor.model/flash': {} },
  timeout: 600,
  retries: 5,
}

async function mountView(path = '/resources?kind=ai') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/resources', component: ResourcesView }],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(ResourcesView, {
    global: {
      plugins: [ElementPlus, router],
      provide: {
        [resourcesApiKey as symbol]: resourcesApi,
        [workflowsApiKey as symbol]: { list: vi.fn().mockResolvedValue([]) },
        [systemApiKey as symbol]: { plugins: vi.fn().mockResolvedValue([]) },
      },
    },
  })
  await flushPromises()
  return { wrapper, router }
}

afterEach(() => vi.clearAllMocks())

describe('resource category actions', () => {
  it('opens the AI category from query state and shows model count', async () => {
    vi.mocked(resourcesApi.list).mockResolvedValue([provider] as never)

    const { wrapper, router } = await mountView()

    expect(router.currentRoute.value.query.kind).toBe('ai')
    expect(vi.mocked(resourcesApi.list).mock.calls.at(-1)?.[0]).toBe('ai')
    expect(wrapper.text()).toContain('添加供应商渠道')
    expect(wrapper.text()).toContain('2 个已配置模型')
    expect(wrapper.text()).toContain('编辑')
    expect(wrapper.text()).toContain('删除')
    expect(wrapper.text()).not.toContain('检查健康')
    expect(wrapper.text()).not.toContain('检查连接')
    expect(resourcesApi.checkAIConnection).not.toHaveBeenCalled()

    wrapper.unmount()
  })

  it('changes the category through the router query instead of local-only state', async () => {
    vi.mocked(resourcesApi.list).mockResolvedValue([])

    const { wrapper, router } = await mountView('/resources?kind=ai')
    await wrapper.get('#tab-channels').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.query.kind).toBe('channels')
    expect(vi.mocked(resourcesApi.list).mock.calls.at(-1)?.[0]).toBe('channels')
    expect(wrapper.text()).toContain('添加通知渠道')

    wrapper.unmount()
  })
})

it('replaces the resource editor session identity and rejects the previous delayed resolve', async () => {
  const first = { ...createResource('sources'), id: 'first', collector: 'mock' } as SourceConfig
  const second = { ...first, id: 'second', display_name: '第二个来源' }
  vi.mocked(resourcesApi.list).mockResolvedValue([first, second])
  let finishFirst!: (value: SourceConfig) => void
  vi.mocked(resourcesApi.resolveSource).mockImplementation((id) =>
    id === 'first'
      ? new Promise((resolve) => {
          finishFirst = resolve
        })
      : Promise.resolve(second),
  )
  const { wrapper } = await mountView('/resources')
  wrapper.getComponent(SourceList).vm.$emit('edit', first)
  await vi.dynamicImportSettled()
  await flushPromises()
  const oldSignal = vi.mocked(resourcesApi.resolveSource).mock.calls[0][2]!
  wrapper.getComponent(SourceList).vm.$emit('edit', second)
  await vi.dynamicImportSettled()
  await flushPromises()
  expect(oldSignal.aborted).toBe(true)
  finishFirst(first)
  await flushPromises()
  const editor = wrapper.getComponent(SourceConfigEditor).props('editor')
  expect(editor.value.value?.id).toBe('second')
  editor.updateBasic({ display_name: '第二个来源草稿' })
  await editor.submit(async () => true)
  expect(resourcesApi.replace).toHaveBeenCalledWith(
    'sources',
    'second',
    expect.objectContaining({ id: 'second', display_name: '第二个来源草稿' }),
  )
  wrapper.unmount()
})
