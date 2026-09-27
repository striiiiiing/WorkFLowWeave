import { effectScope, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import ElementPlus, { ElInput, ElOption, ElRadioGroup, ElSelect } from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import FanInCard from '@/modules/workflows/ui/FanInCard.vue'
import FanOutTaskCard from '@/modules/workflows/ui/FanOutTaskCard.vue'
import PromptOverrides from '@/modules/workflows/ui/PromptOverrides.vue'
import WorkflowBasicInfo from '@/modules/workflows/ui/WorkflowBasicInfo.vue'
import NotificationCard from '@/modules/workflows/ui/NotificationCard.vue'
import { createWorkflow, useWorkflowEditor } from '@/modules/workflows/public'
import { workflowsApiKey } from '@/modules/workflows/api/dependencies'

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

  it('does not offer the first-task model source before a task exists', () => {
    const { editor, scope } = setup()
    editor.toggleFanIn(true)
    const wrapper = mount(FanInCard, {
      props: { editor, configs: [] },
      global: { plugins: [ElementPlus] },
    })
    const modelSource = wrapper.findAllComponents(ElSelect)[1]
    expect(modelSource.props('modelValue')).toBe('$none')
    expect(modelSource.findAllComponents(ElOption).map((option) => option.props('value'))).toEqual([
      '$none',
    ])
    wrapper.unmount()
    scope.stop()
  })

  it('edits shared values and independent empty overrides in advanced mode', async () => {
    const { editor, scope } = setup()
    editor.addTask()
    editor.toggleFanIn(true)
    const basic = mount(WorkflowBasicInfo, {
      props: {
        draft: editor.draft.value!,
        editing: false,
        advanced: true,
        onUpdate: (changes) => editor.update(changes),
      },
      global: {
        plugins: [ElementPlus],
        provide: {
          [workflowsApiKey as symbol]: {
            previewCron: vi.fn().mockResolvedValue({
              description: '每天 09:00',
              timezone: 'Asia/Shanghai',
              next_run_at: '2026-09-28T01:00:00Z',
            }),
          },
        },
      },
    })
    const out = mount(FanOutTaskCard, {
      props: { editor, configs: [], advanced: true },
      global: { plugins: [ElementPlus] },
    })
    const summary = mount(FanInCard, {
      props: { editor, configs: [], advanced: true },
      global: { plugins: [ElementPlus] },
    })
    await basic.findAllComponents(ElInput).at(-2)!.vm.$emit('update:modelValue', 'shared system')
    await basic.findAllComponents(ElInput).at(-1)!.vm.$emit('update:modelValue', 'shared {input}')
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
    await out.findAllComponents(ElInput)[1].vm.$emit('update:modelValue', 'literal {input}')
    expect(editor.draft.value?.analyses[0].user_prompt).toBe('literal {input}')

    await summary.findAllComponents(ElInput)[0].vm.$emit('update:modelValue', 'summary instruction')
    expect(editor.draft.value?.fan_in?.user_prompt).toBe('summary instruction')

    const fanPrompts = summary.getComponent(PromptOverrides)
    await fanPrompts.findAllComponents(ElRadioGroup)[1].vm.$emit('update:modelValue', 'override')
    await nextTick()
    await fanPrompts.findAllComponents(ElInput)[0].vm.$emit('update:modelValue', '')
    expect(editor.draft.value?.fan_in?.input_prompt).toBe('')
    await fanPrompts.findAllComponents(ElRadioGroup)[1].vm.$emit('update:modelValue', 'shared')
    expect(editor.draft.value?.fan_in?.input_prompt).toBeNull()
    basic.unmount()
    out.unmount()
    summary.unmount()
    scope.stop()
  })

  it('reorders fan-in inputs and switches to a reused analysis model', async () => {
    const { editor, scope } = setup()
    editor.addTask()
    editor.addTask()
    editor.toggleFanIn(true)
    expect(editor.draft.value?.fan_in).toMatchObject({
      reuse_from: '$first',
      ai: null,
      model: null,
    })
    const wrapper = mount(FanInCard, {
      props: { editor, configs: [] },
      global: { plugins: [ElementPlus] },
    })
    const modelSource = wrapper.findAllComponents(ElSelect)[1]
    expect(modelSource.props('modelValue')).toBe('$first')
    expect(modelSource.findAllComponents(ElOption).at(-1)!.props('label')).toBe(
      '不复用（可独立选择模型）',
    )
    await modelSource.vm.$emit('update:modelValue', '$none')
    expect(editor.draft.value?.fan_in?.reuse_from).toBeNull()
    editor.updateFanIn({ ai: 'provider', model: 'model' })
    await wrapper.get('[aria-label="上移 task_1"]').trigger('click')
    expect(editor.draft.value?.fan_in?.order).toEqual(['task_1', '$input', 'task_2'])
    await modelSource.vm.$emit('update:modelValue', 'task_2')
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
