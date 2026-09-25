import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, expect, it, vi } from 'vitest'
import { agentsApi, type AgentSettings } from '@/api/agents'
import AgentGlobalSettingsModal from '@/modules/agents/ui/AgentGlobalSettingsModal.vue'
import AgentModelSelect from '@/modules/agents/ui/AgentModelSelect.vue'
import { useAgentSettings } from '@/modules/agents/composables/useAgentSettings'
import { effectScope } from 'vue'
import { readDefaultAgentModel } from '@/domain/agentModels'

const settings: AgentSettings = {
  config: {
    context_window: 200000,
    output_tokens: 4096,
    trigger_tokens: 180000,
    keep_tokens: 40000,
    summary_ai: null,
    summary_context_window: null,
    summary_max_tokens: 4096,
    summary_prompt: 'summary',
    timezone: 'Asia/Shanghai',
    idle_timeout: 300,
    read_concurrency: 4,
    sandbox: { enabled: false, network: false },
  },
  models: [
    {
      reference: 'configured:one',
      ai: 'configured',
      model: 'one',
      provider: 'openai_compatible_api',
    },
  ],
  tools: [
    {
      name: 'plugin',
      plugin: 'agent_plugin',
      description: 'gateway',
      enabled: true,
      execution: null,
      input_schema: {},
      definition_tokens: 12,
      generation: 1,
    },
  ],
  scheduler: {},
  sandbox: { enabled: false, available: false, network: false, status: 'disabled' },
  readonly_paths: [],
}
const wrappers: ReturnType<typeof mount>[] = []
const scopes: ReturnType<typeof effectScope>[] = []
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  scopes.splice(0).forEach((scope) => scope.stop())
  localStorage.clear()
  document.body.innerHTML = ''
})
const button = (text: string) =>
  [...document.querySelectorAll('button')].find((item) => item.textContent?.trim() === text)!
async function setup() {
  vi.spyOn(agentsApi, 'config').mockResolvedValue(settings)
  const scope = effectScope()
  scopes.push(scope)
  const controller = scope.run(() => useAgentSettings(agentsApi))!
  await flushPromises()
  const wrapper = mount(AgentGlobalSettingsModal, {
    props: { modelValue: true, controller },
    attachTo: document.body,
    global: { plugins: [ElementPlus] },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
it('saves the browser default from the real catalog and exposes API errors without closing the draft', async () => {
  const save = vi
    .spyOn(agentsApi, 'updateConfig')
    .mockRejectedValueOnce(new Error('config rejected'))
    .mockResolvedValueOnce(settings.config)
  const wrapper = await setup()
  wrapper.findComponent(AgentModelSelect).vm.$emit('update:modelValue', 'configured:one')
  await flushPromises()
  button('保存全局设置').click()
  await flushPromises()
  expect(document.body.textContent).toContain('config rejected')
  expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  expect(readDefaultAgentModel()).toBe('')
  button('保存全局设置').click()
  await flushPromises()
  expect(save).toHaveBeenCalledTimes(2)
  expect(readDefaultAgentModel()).toBe('configured:one')
  expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([false])
  expect(save.mock.calls[1][0]).not.toHaveProperty('default_model')
})
it('preserves unsaved config edits when tool toggles refresh server metadata', async () => {
  const save = vi.spyOn(agentsApi, 'updateConfig').mockResolvedValue(settings.config)
  const toggle = vi.spyOn(agentsApi, 'updateTool').mockResolvedValue({})
  const wrapper = await setup()
  const input = wrapper.findAllComponents({ name: 'ElInputNumber' })[0]
  input.vm.$emit('update:modelValue', 120000)
  const toolSwitch = wrapper.findAllComponents({ name: 'ElSwitch' })[0]
  toolSwitch.vm.$emit('change', false)
  await flushPromises()
  expect(toggle).toHaveBeenCalledWith('agent_plugin', false)
  expect(document.body.textContent).toContain('按调用动作确定')
  button('保存全局设置').click()
  await flushPromises()
  expect(save).toHaveBeenCalledWith(expect.objectContaining({ context_window: 120000 }))
})
