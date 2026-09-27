import { effectScope, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import ElementPlus, { ElInput, ElRadioGroup, ElSelect } from 'element-plus'
import { describe, expect, it } from 'vitest'
import FanInCard from '@/modules/workflows/ui/FanInCard.vue'
import FanOutTaskCard from '@/modules/workflows/ui/FanOutTaskCard.vue'
import PromptOverrides from '@/modules/workflows/ui/PromptOverrides.vue'
import NotificationCard from '@/modules/workflows/ui/NotificationCard.vue'
import { createWorkflow, useWorkflowEditor } from '@/modules/workflows/public'

function setup() {
  const scope = effectScope()
  const editor = scope.run(() => useWorkflowEditor({ identity: undefined, data: undefined }))!
  return { editor, scope }
}

describe('workflow module UI', () => {
  it('edits fan-out tasks through named controller actions', async () => {
    const { editor, scope } = setup()
    const wrapper = mount(FanOutTaskCard, {
      props: { editor, configs: [] },
      global: { plugins: [ElementPlus] },
    })
    await wrapper.get('button').trigger('click')
    expect(editor.draft.value?.analyses).toHaveLength(1)
    expect(editor.draft.value?.analyses[0].id).toBe('task_1')
    scope.stop()
  })

  it('keeps the fan-in draft while toggling it off and on', async () => {
    const { editor, scope } = setup()
    editor.replace({ ...createWorkflow(), fan_in: editor.createFanIn() })
    const wrapper = mount(FanInCard, {
      props: { editor, configs: [] },
      global: { plugins: [ElementPlus] },
    })
    const toggle = wrapper.get('[role="switch"]')
    await toggle.trigger('click')
    expect(editor.draft.value?.fan_in).toBeNull()
    await toggle.trigger('click')
    expect(editor.draft.value?.fan_in).toMatchObject({ separator: '\n\n' })
    scope.stop()
  })

  it('edits shared values and independent empty overrides in advanced mode', async () => {
    const { editor, scope } = setup()
    editor.addTask()
    editor.toggleFanIn(true)
    const out = mount(FanOutTaskCard, {
      props: { editor, configs: [], advanced: true },
      global: { plugins: [ElementPlus] },
    })
    const summary = mount(FanInCard, {
      props: { editor, configs: [], advanced: true },
      global: { plugins: [ElementPlus] },
    })
    await out.findAllComponents(ElInput)[0].vm.$emit('update:modelValue', 'shared system')
    await out.findAllComponents(ElInput)[1].vm.$emit('update:modelValue', 'shared {input}')
    expect(editor.draft.value).toMatchObject({
      system_prompt: 'shared system',
      input_prompt: 'shared {input}',
    })
    expect(editor.draft.value?.analyses[0].system_prompt).toBeNull()
    expect(editor.draft.value?.fan_in?.input_prompt).toBeNull()

    const taskPrompts = out.getComponent(PromptOverrides)
    await taskPrompts.findAllComponents(ElRadioGroup)[0].vm.$emit('update:modelValue', 'override')
    await nextTick()
    expect(editor.draft.value?.analyses[0].system_prompt).toBe('shared system')
    await taskPrompts.findAllComponents(ElInput)[0].vm.$emit('update:modelValue', '')
    expect(editor.draft.value?.analyses[0].system_prompt).toBe('')
    await taskPrompts.findAllComponents(ElRadioGroup)[1].vm.$emit('update:modelValue', 'override')
    await nextTick()
    expect(editor.draft.value?.analyses[0].input_prompt).toBe('shared {input}')
    await taskPrompts.findAllComponents(ElInput)[2].vm.$emit('update:modelValue', 'literal {input}')
    expect(editor.draft.value?.analyses[0].user_prompt).toBe('literal {input}')

    const fanPrompts = summary.getComponent(PromptOverrides)
    await fanPrompts.findAllComponents(ElRadioGroup)[1].vm.$emit('update:modelValue', 'override')
    await nextTick()
    await fanPrompts.findAllComponents(ElInput)[0].vm.$emit('update:modelValue', '')
    expect(editor.draft.value?.fan_in?.input_prompt).toBe('')
    await fanPrompts.findAllComponents(ElRadioGroup)[1].vm.$emit('update:modelValue', 'shared')
    expect(editor.draft.value?.fan_in?.input_prompt).toBeNull()
    out.unmount()
    summary.unmount()
    scope.stop()
  })

  it('reorders fan-in inputs and switches to a reused analysis model', async () => {
    const { editor, scope } = setup()
    editor.addTask()
    editor.addTask()
    editor.toggleFanIn(true)
    editor.updateFanIn({ reuse_from: null, ai: 'provider', model: 'model' })
    const wrapper = mount(FanInCard, {
      props: { editor, configs: [] },
      global: { plugins: [ElementPlus] },
    })
    await wrapper.get('[aria-label="上移 task_1"]').trigger('click')
    expect(editor.draft.value?.fan_in?.order).toEqual(['task_1', '$input', 'task_2'])
    await wrapper.findAllComponents(ElSelect)[1].vm.$emit('update:modelValue', 'task_2')
    expect(editor.draft.value?.fan_in).toMatchObject({
      reuse_from: 'task_2',
      ai: null,
      model: null,
    })
    wrapper.unmount()
    scope.stop()
  })

  it('does not query system APIs from notification UI', async () => {
    const { editor, scope } = setup()
    editor.replace({ ...createWorkflow(), channels: ['email'] })
    const wrapper = mount(NotificationCard, {
      props: {
        editor,
        channels: [{ id: 'email', channel: 'email', options: {}, timeout: 30, enabled: true }],
        capabilities: [{ kind: 'channel', name: 'email', options_schema: {} }],
      },
      global: { plugins: [ElementPlus] },
    })
    expect(wrapper.text()).toContain('email')
    expect(wrapper.find('.channel-binding-card').exists()).toBe(true)
    expect(wrapper.text()).toContain('编辑')
    expect(wrapper.text()).not.toContain('编辑共用渠道')
    expect(wrapper.text()).toContain('渠道来自资源配置中心并可在多个工作流复用')
    expect(wrapper.find('[aria-label="通知渠道 email"]').exists()).toBe(true)
    await wrapper.get('[aria-label="通知渠道 email"] button').trigger('click')
    expect(wrapper.emitted('edit')?.[0][0]).toMatchObject({ id: 'email' })
    scope.stop()
  })

  it('makes the empty notification binding explicit without inventing a local channel', () => {
    const { editor, scope } = setup()
    const wrapper = mount(NotificationCard, {
      props: { editor, channels: [], capabilities: [] },
      global: { plugins: [ElementPlus] },
    })
    expect(wrapper.text()).toContain('尚未选择通知渠道')
    expect(wrapper.find('.channel-binding-card').exists()).toBe(false)
    scope.stop()
  })
})
