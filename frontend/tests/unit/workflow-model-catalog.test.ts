import { workflowsApi } from '@/api/workflows'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElForm } from 'element-plus'
import { afterEach, expect, it, vi } from 'vitest'
import { resourcesApi } from '@/api/resources'
import FanOutTaskCard from '@/components/workflow/FanOutTaskCard.vue'
import FanInCard from '@/components/workflow/FanInCard.vue'
import WorkflowEditView from '@/views/WorkflowEditView.vue'
import { createFanIn } from '@/domain/workflow'
import type { AIConfig, WorkflowDefinition } from '@/types'

vi.mock('@/api/workflows', () => ({ workflowsApi: { list: vi.fn().mockResolvedValue([]) } }))
vi.mock('@/api/resources', () => ({ resourcesApi: { list: vi.fn() } }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: {} }), useRouter: () => ({}) }))

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
afterEach(() => {
  wrappers.forEach((wrapper) => wrapper.unmount())
  wrappers.length = 0
  vi.clearAllMocks()
})

async function setup() {
  vi.mocked(resourcesApi.list).mockImplementation(async (kind) => (kind === 'ai' ? [provider] : []))
  const wrapper = mount(WorkflowEditView, {
    global: {
      plugins: [ElementPlus],
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
  draft.analyses = [{ id: 'task', ai: provider.id, model: 'original', prompt: '保留提示词' }]
  draft.fan_in = { ...createFanIn(), ai: provider.id, model: 'original', order: ['task'] }
  await flushPromises()
  const expectedDraft = JSON.parse(JSON.stringify(draft))
  let finish!: (value: AIConfig[]) => void
  vi.mocked(resourcesApi.list).mockImplementationOnce(
    () => new Promise<AIConfig[]>((resolve) => (finish = resolve)),
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
  expect(vi.mocked(resourcesApi.list).mock.calls.map(([kind]) => kind)).toEqual([
    'ai',
    'sources',
    'channels',
    'ai',
    'sources',
    'channels',
  ])
  expect(wrapper.text()).not.toContain('刷新模型列表')
  wrapper.unmount()
  wrappers.length = 0
  window.dispatchEvent(new Event('focus'))
  expect(resourcesApi.list).toHaveBeenCalledTimes(6)
  expect(workflowsApi.list).toHaveBeenCalledTimes(2)
})

it('shows catalog update failures and retries without losing edits', async () => {
  const wrapper = await setup()
  const draft = wrapper.getComponent(ElForm).props('model') as WorkflowDefinition
  draft.name = '保留草稿'
  vi.mocked(resourcesApi.list).mockRejectedValueOnce(new Error('目录读取失败'))
  window.dispatchEvent(new Event('focus'))
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('目录读取失败')
  const button = (name: string) => wrapper.findAll('button').find((item) => item.text() === name)!
  expect(button('保存工作流').attributes('disabled')).toBeDefined()
  expect(wrapper.getComponent(ElForm).props('model')).toBe(draft)
  await button('重新加载模型列表').trigger('click')
  await flushPromises()
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  expect(button('保存工作流').attributes('disabled')).toBeUndefined()
  expect(draft.name).toBe('保留草稿')
})
