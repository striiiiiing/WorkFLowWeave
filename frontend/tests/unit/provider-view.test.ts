import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ResourcesView from '@/views/ResourcesView.vue'
import { resourcesApi } from '@/api/resources'

vi.mock('@/api/resources', () => ({
  resourcesApi: {
    list: vi.fn(),
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
    global: { plugins: [ElementPlus, router] },
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
