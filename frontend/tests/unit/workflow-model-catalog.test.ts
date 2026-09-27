import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElForm } from 'element-plus'
import { afterEach, expect, it, vi } from 'vitest'
import FanOutTaskCard from '@/modules/workflows/ui/FanOutTaskCard.vue'
import FanInCard from '@/modules/workflows/ui/FanInCard.vue'
import WorkflowEditPage from '@/pages/workflows/WorkflowEditPage.vue'
import { createFanIn, workflowsApiKey } from '@/modules/workflows/public'
import type { WorkflowsApi, WorkflowDefinition } from '@/modules/workflows/public'
import { resourcesApiKey } from '@/modules/resources/public'
import type { AIConfig, ResourcesApi } from '@/modules/resources/public'
import { systemApiKey } from '@/modules/system/public'
import type { SystemApi } from '@/modules/system/public'

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: {}, query: {} }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}))

const provider: AIConfig = {
  id: 'provider',
  provider: 'openai_compatible_api',
  base_url: null,
  api_key: null,
  system_prompt: '',
  models: { original: {} },
  timeout: 600,
  retries: 5,
}
const wrappers: ReturnType<typeof mount>[] = []
const resourceList = vi.fn()
const workflowList = vi.fn().mockResolvedValue([])
const resourcesApi = {
  list: resourceList,
  resolveSource: vi.fn(),
  discoverAIModels: vi.fn(),
  protectCredential: vi.fn(),
  get: vi.fn(),
  create: vi.fn(),
  replace: vi.fn(),
  delete: vi.fn(),
} as unknown as ResourcesApi
const workflowsApi = {
  list: workflowList,
  get: vi.fn(),
  create: vi.fn(),
  replace: vi.fn(),
  delete: vi.fn(),
} as unknown as WorkflowsApi
const systemApi = {
  plugins: vi.fn().mockResolvedValue([]),
  health: vi.fn(),
  reload: vi.fn(),
} as unknown as SystemApi
afterEach(() => {
  wrappers.forEach((wrapper) => wrapper.unmount())
  wrappers.length = 0
  vi.clearAllMocks()
})

async function setup() {
  resourceList.mockImplementation(async (kind: string) => (kind === 'ai' ? [provider] : []))
  const wrapper = mount(WorkflowEditPage, {
    global: {
      plugins: [ElementPlus],
      provide: {
        [resourcesApiKey as symbol]: resourcesApi,
        [workflowsApiKey as symbol]: workflowsApi,
        [systemApiKey as symbol]: systemApi,
      },
      stubs: {
        RouterLink: { template: '<a><slot /></a>' },
        SourceStepCard: true,
        NotificationCard: true,
        BackupMatrix: true,
      },
    },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

it('updates both model selectors on return without replacing the workflow draft, and stops after leaving', async () => {
  const wrapper = await setup()
  const draft = wrapper.getComponent(ElForm).props('model') as WorkflowDefinition
  draft.name = '未保存的工作流'
  draft.sources = ['logs']
  draft.analyses = [
    {
      id: 'task',
      ai: provider.id,
      model: 'original',
      system_prompt: null,
      input_prompt: null,
      user_prompt: '保留提示词',
    },
  ]
  draft.fan_in = {
    ...createFanIn(),
    reuse_from: null,
    ai: provider.id,
    model: 'original',
    order: ['task'],
  }
  await flushPromises()
  const expectedDraft = JSON.parse(JSON.stringify(draft))
  let finish!: (value: AIConfig[]) => void
  resourceList.mockImplementation((kind: string) =>
    kind === 'ai' ? new Promise<AIConfig[]>((resolve) => (finish = resolve)) : Promise.resolve([]),
  )
  window.dispatchEvent(new Event('focus'))
  await flushPromises()
  expect(wrapper.getComponent(ElForm).props('model')).toBe(draft)
  const updated = [{ ...provider, models: { ...provider.models, added: {} } }]
  finish(updated)
  await flushPromises()
  expect(wrapper.getComponent(FanOutTaskCard).props('configs')).toEqual(updated)
  expect(wrapper.getComponent(FanInCard).props('configs')).toEqual(updated)
  expect(wrapper.getComponent(ElForm).props('model')).toEqual(expectedDraft)
  expect(resourceList.mock.calls.map(([kind]) => kind)).toEqual([
    'sources',
    'channels',
    'ai',
    'sources',
    'channels',
    'ai',
  ])
  expect(wrapper.text()).not.toContain('刷新模型列表')
  wrapper.unmount()
  wrappers.length = 0
  window.dispatchEvent(new Event('focus'))
  expect(resourceList).toHaveBeenCalledTimes(6)
  expect(workflowList).toHaveBeenCalledTimes(2)
})

it('shows catalog update failures and retries without losing edits', async () => {
  const wrapper = await setup()
  const draft = wrapper.getComponent(ElForm).props('model') as WorkflowDefinition
  draft.name = '保留草稿'
  resourceList.mockRejectedValueOnce(new Error('目录读取失败'))
  window.dispatchEvent(new Event('focus'))
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('目录读取失败')
  const button = (name: string) => wrapper.findAll('button').find((item) => item.text() === name)!
  expect(button('保存工作流').attributes('disabled')).toBeDefined()
  expect(wrapper.getComponent(ElForm).props('model')).toBe(draft)
  await button('重新加载资源目录').trigger('click')
  await flushPromises()
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  expect(button('保存工作流').attributes('disabled')).toBeUndefined()
  expect(draft.name).toBe('保留草稿')
})
