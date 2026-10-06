import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { services } from '@/app/services'
import type { AgentEvent, AgentSession, AgentSettings } from '@/modules/agents/public'
import type { SessionRecord } from '@/modules/runs/public'
import AgentPage from '@/pages/agents/AgentPage.vue'
import ContinueInAgent from '@/pages/integrations/ContinueInAgent.vue'
import {
  agentsApiKey,
  AgentHeader,
  AgentModelSelect,
  saveDefaultAgentModel,
} from '@/modules/agents/public'
import { runsApiKey } from '@/modules/runs/public'
import { ApiError } from '@/shared/api/errors'
import { errorFormatterKey } from '@/shared/async/errorFormatter'
const { agentsApi, runsApi } = services
const wrappers: ReturnType<typeof mount>[] = []
const session = (id: string, status = 'completed'): AgentSession => ({
  session_id: id,
  branch_id: id,
  model: 'local:one',
  workflow_session_id: null,
  created_at: 'now',
  updated_at: 'now',
  status,
  turn_id: 't',
  context_budget: null,
  continuable: true,
  history_path: `Runtime/History/${id}/events.jsonl`,
  last_checkpoint_at: 'now',
})
const event = (id: number, type: string, data: Record<string, unknown>): AgentEvent => ({
  id,
  type,
  data,
  session_id: 'parent',
  turn_id: 't',
  at: 'now',
})
const settings = {
  config: { context_window: 200000, output_tokens: 4096, trigger_tokens: 180000 },
  models: [{ reference: 'local:one', provider: 'local', model: 'one', ai: 'local' }],
  tools: [],
  sandbox: { enabled: false },
  scheduler: {},
  readonly_paths: [],
} as unknown as AgentSettings
class Source {
  onopen?: () => void
  onmessage?: (event: { data: string }) => void
  constructor() {
    queueMicrotask(() => this.onopen?.())
  }
  close() {}
}
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
  localStorage.clear()
})
const button = (text: string) =>
  [...document.querySelectorAll('button')].find((element) => element.textContent?.trim() === text)!
async function setup(status = 'completed') {
  vi.stubGlobal('EventSource', Source)
  vi.spyOn(agentsApi, 'list').mockResolvedValue([session('parent')])
  vi.spyOn(agentsApi, 'get').mockImplementation(async (id) => session(id, status))
  vi.spyOn(agentsApi, 'config').mockResolvedValue(settings)
  vi.spyOn(agentsApi, 'history').mockImplementation(async (id) =>
    id === 'parent'
      ? [
          event(1, 'message.user', { message_id: 'original-message', text: 'original' }),
          event(2, 'turn.completed', { checkpoint_id: 'cp' }),
        ]
      : [],
  )
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/agents/:sessionId?', component: { template: '<div />' } },
      { path: '/runs/:sessionId', component: { template: '<div />' } },
    ],
  })
  await router.push('/agents/parent')
  await router.isReady()
  const wrapper = mount(AgentPage, {
    attachTo: document.body,
    global: {
      plugins: [ElementPlus, router],
      provide: {
        [agentsApiKey as symbol]: agentsApi,
        [runsApiKey as symbol]: runsApi,
        [errorFormatterKey as symbol]: (error: unknown) => String(error),
      },
    },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return { wrapper, router }
}
it('previews an edited user message and forks before sending, preserving the parent', async () => {
  const fork = vi.spyOn(agentsApi, 'fork').mockResolvedValue(session('child'))
  const send = vi
    .spyOn(agentsApi, 'send')
    .mockResolvedValue({ session_id: 'child', turn_id: 'new', deduplicated: false })
  const { router } = await setup()
  button('编辑并创建分支').click()
  await flushPromises()
  expect(fork).not.toHaveBeenCalled()
  const editor = document.querySelector('textarea[aria-label="分支消息"]') as HTMLTextAreaElement
  editor.value = 'edited'
  editor.dispatchEvent(new Event('input', { bubbles: true }))
  button('确认创建分支并发送').click()
  await flushPromises()
  expect(fork).toHaveBeenCalledWith('parent', { message_id: 'original-message' })
  expect(send).toHaveBeenCalledWith('child', expect.any(String), 'edited')
  expect(router.currentRoute.value.path).toBe('/agents/child')
  expect(agentsApi.list).toHaveBeenCalled()
})
it('offers compact during a running turn and sends append through the command envelope', async () => {
  const command = vi.spyOn(agentsApi, 'command').mockResolvedValue({
    kind: 'turn',
    priority: 'command',
    result: { session_id: 'parent', turn_id: 't', deduplicated: false, status: 'queued' },
  })
  const compact = vi
    .spyOn(agentsApi, 'compact')
    .mockResolvedValue({ session_id: 'parent', turn_id: 't', deduplicated: false })
  const cancel = vi.spyOn(agentsApi, 'cancel').mockResolvedValue(session('parent', 'cancelled'))
  const { wrapper } = await setup('running')
  await wrapper.get('textarea[aria-label="Agent 消息"]').setValue('/append extra')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(command).toHaveBeenCalledWith('parent', '/append extra', expect.any(String), undefined)
  await wrapper.get('textarea[aria-label="Agent 消息"]').setValue('/compact')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(compact).toHaveBeenCalledWith('parent')
  vi.mocked(agentsApi.get).mockResolvedValueOnce(session('parent', 'cancelled'))
  wrapper
    .get('button[title="停止生成 (Stop)"]')
    .element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  await flushPromises()
  expect(cancel).toHaveBeenCalledWith('parent')
  expect(wrapper.find('button[title="停止生成 (Stop)"]').exists()).toBe(false)
})
it('continues the newest Workflow result directly with a valid default model', async () => {
  saveDefaultAgentModel('local:one')
  const record = (id: string, date: string) =>
    ({
      session_id: id,
      workflow_id: 'wf',
      status: 'completed',
      finished_at: date,
      updated_at: date,
    }) as SessionRecord
  vi.spyOn(runsApi, 'list').mockResolvedValue([
    record('old', '2026-09-21'),
    record('preview', '2026-09-23'),
  ])
  vi.spyOn(agentsApi, 'models').mockResolvedValue(settings.models)
  const create = vi.spyOn(agentsApi, 'create').mockResolvedValue(session('continued'))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }],
  })
  const wrapper = mount(ContinueInAgent, {
    props: { workflowId: 'wf' },
    attachTo: document.body,
    global: {
      plugins: [ElementPlus, router],
      provide: {
        [agentsApiKey as symbol]: agentsApi,
        [runsApiKey as symbol]: runsApi,
        [errorFormatterKey as symbol]: (error: unknown) => String(error),
      },
    },
  })
  wrappers.push(wrapper)
  button('从最新结果继续').click()
  await flushPromises()
  expect(runsApi.list).toHaveBeenCalledWith({ workflow_id: 'wf', limit: 1000 })
  expect(create).toHaveBeenCalledWith({ workflow_session_id: 'preview', model: 'local:one' })
  expect(router.currentRoute.value.path).toBe('/agents/continued')
  expect(wrapper.findComponent(AgentModelSelect).exists()).toBe(false)
})

it('asks for a model when the saved default is no longer available', async () => {
  saveDefaultAgentModel('removed:one')
  vi.spyOn(runsApi, 'list').mockResolvedValue([
    {
      session_id: 'preview',
      workflow_id: 'wf',
      status: 'completed',
      finished_at: '2026-09-23',
      updated_at: '2026-09-23',
    } as SessionRecord,
  ])
  vi.spyOn(agentsApi, 'models').mockResolvedValue(settings.models)
  const create = vi.spyOn(agentsApi, 'create').mockResolvedValue(session('continued'))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }],
  })
  const wrapper = mount(ContinueInAgent, {
    props: { workflowId: 'wf' },
    attachTo: document.body,
    global: {
      plugins: [ElementPlus, router],
      provide: {
        [agentsApiKey as symbol]: agentsApi,
        [runsApiKey as symbol]: runsApi,
        [errorFormatterKey as symbol]: (error: unknown) => String(error),
      },
    },
  })
  wrappers.push(wrapper)
  button('从最新结果继续').click()
  await flushPromises()
  expect(create).not.toHaveBeenCalled()
  expect(document.body.textContent).toContain('默认模型“removed:one”不在当前目录中')
  wrapper.findComponent(AgentModelSelect).vm.$emit('update:modelValue', 'local:one')
  await flushPromises()
  button('创建并继续').click()
  await flushPromises()
  expect(create).toHaveBeenCalledWith({ workflow_session_id: 'preview', model: 'local:one' })
})

it('keeps the same request ID when a send response is lost and the user explicitly retries', async () => {
  const send = vi
    .spyOn(agentsApi, 'send')
    .mockRejectedValueOnce(new TypeError('network lost'))
    .mockResolvedValueOnce({ session_id: 'parent', turn_id: 't', deduplicated: true })
  const { wrapper } = await setup()
  await wrapper.get('textarea[aria-label="Agent 消息"]').setValue('input with uncertain receipt')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.text()).toContain('发送结果未知')
  expect(
    (wrapper.get('textarea[aria-label="Agent 消息"]').element as HTMLTextAreaElement).value,
  ).toBe('input with uncertain receipt')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(send.mock.calls[0][1]).toBe(send.mock.calls[1][1])
  expect(wrapper.text()).not.toContain('发送结果未知')
})

it('creates and switches using the complete resource-center channel reference', async () => {
  const create = vi.spyOn(agentsApi, 'create').mockResolvedValue(session('created'))
  const change = vi.spyOn(agentsApi, 'setModel').mockResolvedValue(session('parent'))
  const { wrapper, router } = await setup()
  vi.mocked(agentsApi.config).mockResolvedValue({
    ...settings,
    models: [
      {
        reference: 'primary:shared',
        provider: 'openai_compatible_api',
        ai: 'primary',
        model: 'shared',
      },
      {
        reference: 'backup:shared',
        provider: 'openai_compatible_api',
        ai: 'backup',
        model: 'shared',
      },
    ],
  })
  button('新会话').click()
  await flushPromises()
  expect(button('确认创建').disabled).toBe(true)
  wrapper.findComponent(AgentModelSelect).vm.$emit('update:modelValue', 'backup:shared')
  await flushPromises()
  button('确认创建').click()
  await flushPromises()
  expect(create).toHaveBeenCalledWith({ model: 'backup:shared' })
  expect(router.currentRoute.value.path).toBe('/agents/created')
  wrapper.findComponent(AgentHeader).vm.$emit('changeModel', 'primary:shared')
  await flushPromises()
  expect(change).toHaveBeenCalledWith('created', 'primary:shared')
})

it('loads workflow history from the header and exposes request failures', async () => {
  const list = vi.spyOn(runsApi, 'list').mockRejectedValue(new Error('history offline'))
  const { wrapper } = await setup()
  await wrapper.get('[aria-label="Workflow 历史"]').trigger('click')
  await flushPromises()
  expect(list).toHaveBeenCalledWith({ limit: 100 })
  expect(document.body.textContent).toContain('history offline')
  list.mockResolvedValue([])
  button('刷新历史').click()
  await flushPromises()
  expect(document.body.textContent).toContain('暂无 Workflow 运行记录')
})

it('retains the created branch and request ID when the edited message response is lost', async () => {
  const fork = vi.spyOn(agentsApi, 'fork').mockResolvedValue(session('child'))
  const send = vi
    .spyOn(agentsApi, 'send')
    .mockRejectedValueOnce(new TypeError('network lost'))
    .mockResolvedValueOnce({ session_id: 'child', turn_id: 'new', deduplicated: true })
  const { router } = await setup()
  button('编辑并创建分支').click()
  await flushPromises()
  button('确认创建分支并发送').click()
  await flushPromises()
  expect(document.body.textContent).toContain('network lost')
  button('确认创建分支并发送').click()
  await flushPromises()
  expect(fork).toHaveBeenCalledTimes(1)
  expect(send.mock.calls[0]).toEqual(send.mock.calls[1])
  expect(router.currentRoute.value.path).toBe('/agents/child')
})

it('queues plain input while running and retains running state on a queued receipt', async () => {
  const command = vi.spyOn(agentsApi, 'command').mockResolvedValue({
    kind: 'turn',
    priority: 'command',
    result: { session_id: 'parent', turn_id: 't', status: 'queued', deduplicated: false },
  })
  const { wrapper } = await setup('running')
  await wrapper.get('textarea[aria-label="Agent 消息"]').setValue('补充日志范围')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(command).toHaveBeenCalledWith(
    'parent',
    '/append 补充日志范围',
    expect.any(String),
    undefined,
  )
  expect(wrapper.get('[aria-label="追加到队列"]').exists()).toBe(true)
})

it('preselects the persistent default in new sessions without linking to the demo', async () => {
  saveDefaultAgentModel('local:one')
  const create = vi.spyOn(agentsApi, 'create').mockResolvedValue(session('created'))
  const { wrapper } = await setup()
  expect(wrapper.find('a[href="/agent-demo"]').exists()).toBe(false)
  button('新会话').click()
  await flushPromises()
  expect(create).toHaveBeenCalledWith({ model: 'local:one' })
  expect(document.body.textContent).not.toContain('创建 Agent 分析会话')
})

it('keeps drafts and unknown send receipts with their originating session during navigation', async () => {
  const send = vi
    .spyOn(agentsApi, 'send')
    .mockRejectedValueOnce(new TypeError('network lost'))
    .mockResolvedValueOnce({ session_id: 'parent', turn_id: 't', deduplicated: true })
  const { wrapper, router } = await setup()
  await wrapper.get('textarea[aria-label="Agent 消息"]').setValue('parent draft')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  const requestId = send.mock.calls[0][1]
  await router.push('/agents/another')
  await flushPromises()
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('')
  expect(wrapper.text()).not.toContain('发送结果未知')
  await wrapper.get('textarea').setValue('another draft')
  await router.push('/agents/parent')
  await flushPromises()
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('parent draft')
  expect(wrapper.text()).toContain('发送结果未知')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(send.mock.calls[1][1]).toBe(requestId)
})

it('treats an HTTP gateway timeout as unknown and retries with the same request ID', async () => {
  const send = vi
    .spyOn(agentsApi, 'send')
    .mockRejectedValueOnce(
      new ApiError(504, {
        code: 'gateway_timeout',
        message: 'Gateway Timeout',
        details: {},
      }),
    )
    .mockResolvedValueOnce({ session_id: 'parent', turn_id: 't', deduplicated: true })
  const { wrapper } = await setup()
  await wrapper.get('textarea[aria-label="Agent 消息"]').setValue('gateway timeout input')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.text()).toContain('发送结果未知')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(send.mock.calls[1]).toEqual(send.mock.calls[0])
})

it('asks to inspect sessions instead of retrying an uncertain workflow creation', async () => {
  const command = vi.spyOn(agentsApi, 'command').mockRejectedValue(new TypeError('network lost'))
  const { wrapper } = await setup()
  await wrapper.get('textarea[aria-label="Agent 消息"]').setValue('/workflow run-1')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.text()).toContain('请先检查会话列表')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(command).toHaveBeenCalledTimes(1)
})
