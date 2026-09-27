import { defineComponent, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElForm, ElInput, ElSwitch } from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import FanInCard from '@/modules/workflows/ui/FanInCard.vue'
import FanOutTaskCard from '@/modules/workflows/ui/FanOutTaskCard.vue'
import NotificationCard from '@/modules/workflows/ui/NotificationCard.vue'
import SourceStepCard from '@/modules/workflows/ui/SourceStepCard.vue'
import { createFanIn, createWorkflow, useWorkflowEditor } from '@/modules/workflows/public'
import type { CapabilityDescription } from '@/shared/types'

const plugins = vi.hoisted(() => ({ list: vi.fn() }))
vi.mock('@/app/services', () => ({ systemApi: { plugins: plugins.list } }))

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
    const initial = {
      ...createWorkflow(),
      fan_in: { ...createFanIn(), order: ['task'], input_prompt: 'keep me', separator: '---' },
    }
    let editor!: ReturnType<typeof useWorkflowEditor>
    const wrapper = mount(
      defineComponent({
        components: { FanInCard },
        setup: () => {
          editor = useWorkflowEditor({ identity: undefined })
          editor.replace(initial)
          return { editor }
        },
        template: '<FanInCard :editor="editor" :configs="[]" />',
      }),
      { global },
    )
    await wrapper
      .findComponent(FanInCard)
      .findComponent(ElSwitch)
      .vm.$emit('update:modelValue', false)
    expect(editor.draft.value?.fan_in).toBeNull()
    await wrapper
      .findComponent(FanInCard)
      .findComponent(ElSwitch)
      .vm.$emit('update:modelValue', true)
    expect(editor.draft.value?.fan_in).toMatchObject({
      order: ['task'],
      input_prompt: 'keep me',
      separator: '---',
    })
    wrapper.unmount()
  })

  it('does not rewrite fan-in references while a task ID is temporarily duplicated', async () => {
    const initial = {
      ...createWorkflow(),
      analyses: [
        {
          id: 'first',
          ai: '',
          model: '',
          system_prompt: null,
          input_prompt: null,
          user_prompt: '',
        },
        {
          id: 'second',
          ai: '',
          model: '',
          system_prompt: null,
          input_prompt: null,
          user_prompt: '',
        },
      ],
      fan_in: { ...createFanIn(), order: ['first', 'second'] },
    }
    let editor!: ReturnType<typeof useWorkflowEditor>
    const wrapper = mount(
      defineComponent({
        components: { FanOutTaskCard },
        setup: () => {
          editor = useWorkflowEditor({ identity: undefined })
          editor.replace(initial)
          return { editor }
        },
        template:
          '<el-form :model="editor.draft"><FanOutTaskCard :editor="editor" :configs="[]" /></el-form>',
      }),
      { global },
    )
    const inputs = wrapper.findComponent(FanOutTaskCard).findAllComponents(ElInput)
    await inputs[0].vm.$emit('update:modelValue', 'second')
    expect(editor.draft.value?.analyses[0].id).toBe('first')
    expect(editor.taskIdError(0)).toContain('任务编号不能重名')
    expect(wrapper.findComponent(FanOutTaskCard).find('.el-form-item.is-error').exists()).toBe(true)
    expect(editor.draft.value?.fan_in?.order).toEqual(['first', 'second'])
    await inputs[0].vm.$emit('update:modelValue', 'renamed')
    expect(editor.draft.value?.fan_in?.order).toEqual(['renamed', 'second'])
    editor.updateFanIn({ order: ['second'] })
    await inputs[0].vm.$emit('update:modelValue', 'unselected')
    expect(editor.draft.value?.fan_in?.order).toEqual(['second'])
    await inputs[2].vm.$emit('update:modelValue', 'selected')
    expect(editor.draft.value?.fan_in?.order).toEqual(['selected'])
    wrapper.unmount()
  })

  it('shows workflow-scoped channel options and disabled resource placeholders', async () => {
    plugins.list.mockResolvedValue([
      capability('collector', 'mock'),
      capability('channel', 'email'),
    ])
    const initial = {
      ...createWorkflow(),
      sources: ['disabled-source'],
      channels: ['disabled-channel'],
    }
    let editor!: ReturnType<typeof useWorkflowEditor>
    const wrapper = mount(
      defineComponent({
        components: { SourceStepCard, NotificationCard },
        setup: () => {
          editor = useWorkflowEditor({ identity: undefined })
          editor.replace(initial)
          return { editor, gateway: { resolve: vi.fn(), save: vi.fn() }, protect: vi.fn() }
        },
        template:
          '<el-form :model="editor.draft"><SourceStepCard :editor="editor" :sources="sources" :gateway="gateway" :capabilities="[]" :protect="protect" /><NotificationCard :editor="editor" :channels="channels" :capabilities="capabilities" /></el-form>',
        data: () => ({
          sources: [{ id: 'disabled-source', collector: 'mock', enabled: false }],
          channels: [{ id: 'disabled-channel', channel: 'email', enabled: false }],
          capabilities: [capability('channel', 'email')],
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
    expect(editor.draft.value?.channel_overrides).toEqual({ 'disabled-channel': { options: {} } })
    expect(wrapper.text()).toContain('recipient')
    wrapper.unmount()
  })
})
