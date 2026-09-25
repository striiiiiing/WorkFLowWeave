import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import App from '@/app/App.vue'
import { router as applicationRouter } from '@/app/router'
import { services } from '@/app/services'
import { agentsApiKey, type AgentSession, type AgentSettings } from '@/modules/agents/public'
import { runsApiKey } from '@/modules/runs/public'

const current = (id: string): AgentSession => ({
  session_id: id,
  branch_id: id,
  model: 'local:one',
  workflow_session_id: null,
  created_at: 'now',
  updated_at: 'now',
  status: 'completed',
  turn_id: 't',
  context_budget: null,
  continuable: true,
  history_path: `History/${id}`,
  last_checkpoint_at: 'now',
})
const settings = {
  config: { context_window: null, output_tokens: 4096, trigger_tokens: 10000 },
  models: [{ reference: 'local:one', provider: 'local', ai: 'local', model: 'one' }],
  tools: [],
  scheduler: {},
  sandbox: { enabled: false, network: false, available: false, status: 'disabled' },
  readonly_paths: [],
} as AgentSettings
class Source {
  onopen?: () => void
  onmessage?: (event: { data: string }) => void
  close() {}
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

it('keeps one AgentPage instance across A -> B -> A and releases it on exit', async () => {
  vi.stubGlobal('EventSource', Source)
  vi.spyOn(services.agentsApi, 'list').mockResolvedValue([current('A'), current('B')])
  vi.spyOn(services.agentsApi, 'history').mockResolvedValue([])
  vi.spyOn(services.agentsApi, 'get').mockImplementation(async (id) => current(id))
  const config = vi.spyOn(services.agentsApi, 'config').mockResolvedValue(settings)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: applicationRouter.options.routes,
  })
  await router.push('/agents/A')
  await router.isReady()
  const wrapper = mount(App, {
    attachTo: document.body,
    global: {
      plugins: [ElementPlus, router],
      provide: {
        [agentsApiKey as symbol]: services.agentsApi,
        [runsApiKey as symbol]: services.runsApi,
      },
    },
  })
  await flushPromises()
  const input = () => wrapper.get('textarea[aria-label="Agent 消息"]')
  await input().setValue('draft A')
  await router.push('/agents/B')
  await flushPromises()
  expect((input().element as HTMLTextAreaElement).value).toBe('')
  await input().setValue('draft B')
  await router.push('/agents/A')
  await flushPromises()
  expect(router.currentRoute.value.params.sessionId).toBe('A')
  expect(config).toHaveBeenCalledTimes(1)
  await router.push('/missing')
  await flushPromises()
  await router.push('/agents/B')
  await flushPromises()
  expect((input().element as HTMLTextAreaElement).value).toBe('')
  wrapper.unmount()
})
