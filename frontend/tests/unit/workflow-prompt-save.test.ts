import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElForm, ElInput, ElRadioGroup } from 'element-plus'
import { expect, it, vi } from 'vitest'
import WorkflowEditPage from '@/pages/workflows/WorkflowEditPage.vue'
import FanOutTaskCard from '@/modules/workflows/ui/FanOutTaskCard.vue'
import FanInCard from '@/modules/workflows/ui/FanInCard.vue'
import PromptOverrides from '@/modules/workflows/ui/PromptOverrides.vue'
import WorkflowBasicInfo from '@/modules/workflows/ui/WorkflowBasicInfo.vue'
import { createFanIn, createWorkflow, workflowsApiKey } from '@/modules/workflows/public'
import type { WorkflowDefinition, WorkflowsApi } from '@/modules/workflows/public'
import { resourcesApiKey } from '@/modules/resources/public'
import type { AIConfig, ResourcesApi } from '@/modules/resources/public'
import { systemApiKey } from '@/modules/system/public'
import type { SystemApi } from '@/modules/system/public'

const navigate = vi.hoisted(() => vi.fn())
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: 'prompt_workflow' }, query: {} }),
  useRouter: () => ({ replace: vi.fn(), push: navigate }),
}))

const provider: AIConfig = {
  id: 'provider',
  provider: 'openai_compatible_api',
  base_url: null,
  api_key: null,
  system_prompt: '',
  models: { model: {} },
  timeout: 600,
  retries: 5,
}

it('saves layered prompts and reopens the same workflow without legacy prompt fields', async () => {
  const initial: WorkflowDefinition = {
    ...createWorkflow(),
    id: 'prompt_workflow',
    sources: ['logs'],
    analyses: [
      {
        id: 'first',
        ai: 'provider',
        model: 'model',
        system_prompt: null,
        input_prompt: null,
        user_prompt: '',
      },
      {
        id: 'second',
        ai: 'provider',
        model: 'model',
        system_prompt: null,
        input_prompt: null,
        user_prompt: '',
      },
    ],
    fan_in: createFanIn(),
  }
  let saved = structuredClone(initial)
  const replace = vi.fn(async (_id: string, value: WorkflowDefinition) => {
    saved = JSON.parse(JSON.stringify(value)) as WorkflowDefinition
    return structuredClone(saved)
  })
  const workflowsApi = {
    list: vi.fn().mockResolvedValue([]),
    get: vi.fn(async () => structuredClone(saved)),
    replace,
  } as unknown as WorkflowsApi
  const resourcesApi = {
    list: vi.fn(async (kind: string) => (kind === 'ai' ? [provider] : [])),
    protectCredential: vi.fn(),
  } as unknown as ResourcesApi
  const systemApi = { plugins: vi.fn().mockResolvedValue([]) } as unknown as SystemApi
  const options = {
    global: {
      plugins: [ElementPlus],
      provide: {
        [workflowsApiKey as symbol]: workflowsApi,
        [resourcesApiKey as symbol]: resourcesApi,
        [systemApiKey as symbol]: systemApi,
      },
      stubs: {
        RouterLink: { template: '<a><slot /></a>' },
        SourceStepCard: true,
        NotificationCard: true,
        BackupMatrix: true,
      },
    },
  }
  const wrapper = mount(WorkflowEditPage, options)
  await flushPromises()
  const basic = wrapper.getComponent(WorkflowBasicInfo)
  expect(basic.findAllComponents(ElInput).at(-1)!.props('modelValue')).toBe('')
  expect(basic.text()).not.toContain('输入模板')
  const taskCard = wrapper.getComponent(FanOutTaskCard)
  const fanIn = wrapper.getComponent(FanInCard)
  expect(taskCard.text()).toContain('提示词')
  expect(fanIn.text()).toContain('提示词')
  await taskCard.findAllComponents(ElInput)[1].vm.$emit('update:modelValue', 'literal {input}')
  await fanIn.findAllComponents(ElInput)[0].vm.$emit('update:modelValue', 'summary instruction')
  await wrapper.get('[aria-label="高级模式"]').trigger('click')
  await basic.findAllComponents(ElInput).at(-2)!.vm.$emit('update:modelValue', 'shared system')
  await basic.findAllComponents(ElInput).at(-1)!.vm.$emit('update:modelValue', 'shared {input}')
  const first = taskCard.findAllComponents(PromptOverrides)[0]
  await first.findAllComponents(ElRadioGroup)[0].vm.$emit('update:modelValue', 'override')
  await flushPromises()
  await first.findAllComponents(ElInput)[0].vm.$emit('update:modelValue', '')
  const fanPrompts = fanIn.getComponent(PromptOverrides)
  await fanPrompts.findAllComponents(ElRadioGroup)[1].vm.$emit('update:modelValue', 'override')
  await flushPromises()
  await fanPrompts.findAllComponents(ElInput)[0].vm.$emit('update:modelValue', '')
  await fanIn.get('[aria-label="上移 second"]').trigger('click')
  await wrapper
    .findAll('button')
    .find((button) => button.text() === '保存工作流')!
    .trigger('click')
  await flushPromises()

  expect(replace).toHaveBeenCalledOnce()
  expect(navigate).toHaveBeenCalledWith('/workflows')
  expect(saved).toMatchObject({
    system_prompt: 'shared system',
    input_prompt: 'shared {input}',
    analyses: [
      { system_prompt: '', input_prompt: null, user_prompt: 'literal {input}' },
      { system_prompt: null, input_prompt: null, user_prompt: '' },
    ],
    fan_in: {
      input_prompt: '',
      user_prompt: 'summary instruction',
      reuse_from: '$first',
      order: ['$input', 'second', 'first'],
    },
  })
  expect(JSON.stringify(saved)).not.toContain('"prompt"')
  wrapper.unmount()

  const reopened = mount(WorkflowEditPage, options)
  await flushPromises()
  expect(reopened.getComponent(ElForm).props('model')).toEqual(saved)
  reopened.unmount()
})
