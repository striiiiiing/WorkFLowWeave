import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, expect, it, vi } from 'vitest'
import ContinueInAgent from '@/pages/integrations/ContinueInAgent.vue'
import { agentsApiKey, saveDefaultAgentModel } from '@/modules/agents/public'
import type { AgentSession } from '@/modules/agents/public'
import type { SessionRecord } from '@/modules/runs/public'
import { runsApiKey } from '@/modules/runs/public'
import { errorFormatterKey } from '@/shared/async/errorFormatter'

const source: SessionRecord = {
  session_id: 'run-1',
  workflow_id: 'daily',
  workflow_name: '日报',
  version: 3,
  status: 'completed',
  stage: 'finish',
  created_at: 'now',
  updated_at: 'now',
  finished_at: 'now',
  error: null,
  artifacts: [],
  snapshot_availability: 'available',
}

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
  document.body.innerHTML = ''
})

it('creates an Agent from the already loaded run and routes to the new session', async () => {
  saveDefaultAgentModel('local:one')
  const created: AgentSession = {
    session_id: 'agent-1',
    branch_id: 'agent-1',
    model: 'local:one',
    workflow_session_id: 'run-1',
    created_at: 'now',
    updated_at: 'now',
    status: 'created',
    turn_id: null,
    context_budget: null,
    continuable: true,
    history_path: 'History/agent-1',
    last_checkpoint_at: null,
  }
  const models = vi
    .fn()
    .mockResolvedValue([{ reference: 'local:one', provider: 'local', ai: 'local', model: 'one' }])
  const create = vi.fn().mockResolvedValue(created)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/runs/:id', component: { template: '<div />' } },
      { path: '/agents/:sessionId', component: { template: '<div />' } },
    ],
  })
  await router.push('/runs/run-1')
  const wrapper = mount(ContinueInAgent, {
    props: { session: source },
    attachTo: document.body,
    global: {
      plugins: [ElementPlus, router],
      provide: {
        [agentsApiKey as symbol]: { models, create },
        [runsApiKey as symbol]: { list: vi.fn(), get: vi.fn() },
        [errorFormatterKey as symbol]: (error: unknown) => String(error),
      },
    },
  })

  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(models).toHaveBeenCalledTimes(1)
  expect(document.body.textContent).not.toContain('创建并继续')
  expect(create).toHaveBeenCalledWith({ workflow_session_id: 'run-1', model: 'local:one' })
  expect(router.currentRoute.value.fullPath).toBe('/agents/agent-1')
  wrapper.unmount()
})

it('shows a stale default and keeps creation disabled until a current model is selected', async () => {
  saveDefaultAgentModel('deleted:one')
  const models = vi
    .fn()
    .mockResolvedValue([
      { reference: 'current:one', provider: 'local', ai: 'current', model: 'one' },
    ])
  const create = vi.fn()
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/runs/:id', component: { template: '<div />' } }],
  })
  await router.push('/runs/run-1')
  const wrapper = mount(ContinueInAgent, {
    props: { session: source },
    attachTo: document.body,
    global: {
      plugins: [ElementPlus, router],
      provide: {
        [agentsApiKey as symbol]: { models, create },
        [runsApiKey as symbol]: { list: vi.fn(), get: vi.fn() },
        [errorFormatterKey as symbol]: (error: unknown) => String(error),
      },
    },
  })
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(document.body.textContent).toContain('默认模型“deleted:one”不在当前目录中')
  expect(document.body.textContent).toContain('创建并继续')
  expect(create).not.toHaveBeenCalled()
  wrapper.unmount()
})
