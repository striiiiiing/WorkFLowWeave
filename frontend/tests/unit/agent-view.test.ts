import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { agentsApi, type AgentEvent, type AgentSession, type AgentSettings } from '@/api/agents'
import { runsApi } from '@/api/runs'
import type { SessionRecord } from '@/types'
import AgentsView from '@/views/AgentsView.vue'
import AgentContinueButton from '@/components/agent/AgentContinueButton.vue'
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
  onmessage?: (event: { data: string }) => void
  close() {}
}
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})
const button = (text: string) =>
  [...document.querySelectorAll('button')].find((element) => element.textContent?.trim() === text)!
async function setup() {
  vi.stubGlobal('EventSource', Source)
  vi.spyOn(agentsApi, 'list').mockResolvedValue([session('parent')])
  vi.spyOn(agentsApi, 'get').mockImplementation(async (id) => session(id))
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
    routes: [{ path: '/agents/:sessionId?', component: { template: '<div />' } }],
  })
  await router.push('/agents/parent')
  await router.isReady()
  const wrapper = mount(AgentsView, {
    attachTo: document.body,
    global: { plugins: [ElementPlus, router] },
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
  const { wrapper } = await setup()
  await wrapper.get('textarea[aria-label="Agent 消息"]').setValue('/append extra')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(command).toHaveBeenCalledWith('parent', '/append extra', expect.any(String))
  expect(button('压缩').disabled).toBe(false)
  button('压缩').click()
  await flushPromises()
  expect(compact).toHaveBeenCalledWith('parent')
  button('停止').click()
  await flushPromises()
  expect(cancel).toHaveBeenCalledWith('parent')
  expect(button('停止').disabled).toBe(true)
})
it('previews the newest Workflow result and freezes that source and selected model at creation', async () => {
  const record = (id: string, date: string) =>
    ({
      session_id: id,
      workflow_id: 'wf',
      status: 'completed',
      finished_at: date,
      updated_at: date,
    }) as SessionRecord
  const list = vi
    .spyOn(runsApi, 'list')
    .mockResolvedValue([record('old', '2026-09-21'), record('preview', '2026-09-23')])
  vi.spyOn(agentsApi, 'models').mockResolvedValue(settings.models)
  const create = vi.spyOn(agentsApi, 'create').mockResolvedValue(session('continued'))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }],
  })
  const wrapper = mount(AgentContinueButton, {
    props: { workflowId: 'wf' },
    attachTo: document.body,
    global: { plugins: [ElementPlus, router] },
  })
  wrappers.push(wrapper)
  button('从最新结果继续').click()
  await flushPromises()
  expect(document.body.textContent).toContain('wf / preview')
  list.mockResolvedValue([record('later', '2026-09-24')])
  wrapper.findComponent({ name: 'ElSelect' }).vm.$emit('update:modelValue', 'local:one')
  button('创建并继续').click()
  await flushPromises()
  expect(create).toHaveBeenCalledWith({ workflow_session_id: 'preview', model: 'local:one' })
  expect(router.currentRoute.value.path).toBe('/agents/continued')
})

it('keeps the same request ID when a send response is lost and the user explicitly retries', async () => {
  const command = vi
    .spyOn(agentsApi, 'command')
    .mockRejectedValueOnce(new TypeError('network lost'))
    .mockResolvedValueOnce({
      kind: 'turn',
      priority: 'conversation',
      result: { session_id: 'parent', turn_id: 't', deduplicated: true },
    })
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
  expect(command.mock.calls[0][2]).toBe(command.mock.calls[1][2])
  expect(wrapper.text()).not.toContain('发送结果未知')
})
