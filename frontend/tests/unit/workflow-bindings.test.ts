import { defineComponent, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElForm, ElInput, ElSwitch } from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import FanInCard from '@/components/workflow/FanInCard.vue'
import FanOutTaskCard from '@/components/workflow/FanOutTaskCard.vue'
import NotificationCard from '@/components/workflow/NotificationCard.vue'
import SourceStepCard from '@/components/workflow/SourceStepCard.vue'
import { createFanIn, createWorkflow } from '@/domain/workflow'
import type { CapabilityDescription } from '@/types'

const plugins = vi.hoisted(() => ({ list: vi.fn() }))
vi.mock('@/api/system', () => ({ systemApi: { plugins: plugins.list } }))

const global = { plugins: [ElementPlus] }
const capability = (kind: 'collector' | 'channel', name: string): CapabilityDescription => ({
  kind,
  name,
  plugin: 'test',
  description: '',
  capabilities: [],
  options_schema:
    kind === 'channel'
      ? {
          type: 'object',
          properties: {
            recipient: { type: 'string', 'x-logagent-workflow': true, description: '收件人' },
          },
        }
      : { type: 'object', properties: {} },
  setters_schema: null,
  fields: [],
  count_unit: null,
})

afterEach(() => vi.clearAllMocks())

describe('workflow bindings', () => {
  it('keeps the fan-in draft when temporarily disabled and restored', async () => {
    const workflow = ref({
      ...createWorkflow(),
      fan_in: { ...createFanIn(), order: ['task'], prompt: 'keep me', separator: '---' },
    })
    const wrapper = mount(
      defineComponent({
        components: { FanInCard },
        setup: () => ({ workflow }),
        template: '<FanInCard v-model="workflow" :configs="[]" />',
      }),
      { global },
    )
    await wrapper.findComponent(FanInCard).findComponent(ElSwitch).vm.$emit('change', false)
    expect(workflow.value.fan_in).toBeNull()
    await wrapper.findComponent(FanInCard).findComponent(ElSwitch).vm.$emit('change', true)
    expect(workflow.value.fan_in).toMatchObject({
      order: ['task'],
      prompt: 'keep me',
      separator: '---',
    })
    wrapper.unmount()
  })

  it('does not rewrite fan-in references while a task ID is temporarily duplicated', async () => {
    const workflow = ref({
      ...createWorkflow(),
      analyses: [
        { id: 'first', ai: '', model: '', prompt: '{input}' },
        { id: 'second', ai: '', model: '', prompt: '{input}' },
      ],
      fan_in: { ...createFanIn(), order: ['first', 'second'] },
    })
    const wrapper = mount(
      defineComponent({
        components: { FanOutTaskCard },
        setup: () => ({ workflow }),
        template:
          '<el-form :model="workflow"><FanOutTaskCard v-model="workflow" :configs="[]" /></el-form>',
      }),
      { global },
    )
    const inputs = wrapper.findComponent(FanOutTaskCard).findAllComponents(ElInput)
    await inputs[0].vm.$emit('update:modelValue', 'second')
    expect(workflow.value.analyses[0].id).toBe('first')
    let valid = true
    let validationMessage = ''
    await wrapper.findComponent(ElForm).vm.validateField('analyses.0.id', (result, fields) => {
      valid = result
      validationMessage = fields?.['analyses.0.id']?.[0]?.message ?? ''
    })
    await flushPromises()
    expect(valid).toBe(false)
    expect(validationMessage).toContain('任务编号不能重名')
    expect(wrapper.findComponent(FanOutTaskCard).find('.el-form-item.is-error').exists()).toBe(true)
    expect(workflow.value.fan_in?.order).toEqual(['first', 'second'])
    await inputs[0].vm.$emit('update:modelValue', 'renamed')
    expect(workflow.value.fan_in?.order).toEqual(['renamed', 'second'])
    workflow.value.fan_in!.order = ['second']
    await inputs[0].vm.$emit('update:modelValue', 'unselected')
    expect(workflow.value.fan_in?.order).toEqual(['second'])
    await inputs[2].vm.$emit('update:modelValue', 'selected')
    expect(workflow.value.fan_in?.order).toEqual(['selected'])
    wrapper.unmount()
  })

  it('shows workflow-scoped channel options and disabled resource placeholders', async () => {
    plugins.list.mockResolvedValue([
      capability('collector', 'mock'),
      capability('channel', 'email'),
    ])
    const workflow = ref({
      ...createWorkflow(),
      sources: ['disabled-source'],
      channels: ['disabled-channel'],
    })
    const wrapper = mount(
      defineComponent({
        components: { SourceStepCard, NotificationCard },
        setup: () => ({ workflow }),
        template:
          '<el-form :model="workflow"><SourceStepCard v-model="workflow" :sources="sources" /><NotificationCard v-model="workflow" :channels="channels" /></el-form>',
        data: () => ({
          sources: [{ id: 'disabled-source', collector: 'mock', enabled: false }],
          channels: [{ id: 'disabled-channel', channel: 'email', enabled: false }],
        }),
      }),
      { global },
    )
    await flushPromises()
    expect(wrapper.text()).toContain('已停用')
    expect(wrapper.text()).toContain('重新启用后会恢复原设置')
    await wrapper
      .findComponent(NotificationCard)
      .findComponent(ElSwitch)
      .vm.$emit('update:modelValue', true)
    await flushPromises()
    expect(workflow.value.channel_overrides).toEqual({ 'disabled-channel': { options: {} } })
    expect(wrapper.text()).toContain('recipient')
    wrapper.unmount()
  })
})
