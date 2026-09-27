import { defineComponent, nextTick, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElDatePicker, ElForm, ElInput, ElInputNumber, ElSelect } from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import WorkflowBasicInfo from '@/modules/workflows/ui/WorkflowBasicInfo.vue'
import { workflowsApiKey } from '@/modules/workflows/api/dependencies'
import { createWorkflow, type WorkflowSchedule } from '@/modules/workflows/public'

function setup(schedule: WorkflowSchedule | null = null) {
  const draft = ref({ ...createWorkflow(), schedule })
  const previewCron = vi.fn().mockResolvedValue({
    description: '每天 9:00',
    timezone: 'Asia/Shanghai',
    next_run_at: '2026-09-28T01:00:00Z',
  })
  const wrapper = mount(
    defineComponent({
      components: { WorkflowBasicInfo },
      setup: () => ({ draft }),
      template:
        '<el-form :model="draft"><WorkflowBasicInfo :draft="draft" :editing="false" :advanced="false" @update="draft = { ...draft, ...$event }" /></el-form>',
    }),
    {
      global: {
        plugins: [ElementPlus],
        provide: { [workflowsApiKey as symbol]: { previewCron } },
      },
    },
  )
  return { draft, previewCron, wrapper, basic: wrapper.getComponent(WorkflowBasicInfo) }
}

afterEach(() => {
  vi.useRealTimers()
})

describe('workflow schedule editor', () => {
  it('edits an aware one-time instant and a positive interval with units', async () => {
    const { draft, basic, wrapper } = setup()
    expect(draft.value.schedule).toBeNull()
    basic.findAllComponents(ElSelect)[0].vm.$emit('update:modelValue', 'at')
    await nextTick()
    expect(draft.value.schedule).toEqual({ type: 'at', at: '' })
    expect(
      await wrapper
        .getComponent(ElForm)
        .vm.validate()
        .catch(() => false),
    ).toBe(false)

    basic.getComponent(ElDatePicker).vm.$emit('update:modelValue', new Date('2026-10-01T12:30:00Z'))
    await nextTick()
    expect(draft.value.schedule).toEqual({ type: 'at', at: '2026-10-01T12:30:00.000Z' })

    basic.findAllComponents(ElSelect)[0].vm.$emit('update:modelValue', 'every')
    await nextTick()
    expect(draft.value.schedule).toEqual({ type: 'every', every_seconds: 0 })
    expect(
      await wrapper
        .getComponent(ElForm)
        .vm.validate()
        .catch(() => false),
    ).toBe(false)
    basic.findAllComponents(ElSelect)[1].vm.$emit('update:modelValue', 60)
    basic.getComponent(ElInputNumber).vm.$emit('update:modelValue', 2)
    await nextTick()
    expect(draft.value.schedule).toEqual({ type: 'every', every_seconds: 120 })
    basic.findAllComponents(ElSelect)[1].vm.$emit('update:modelValue', 1)
    await nextTick()
    expect(basic.getComponent(ElInputNumber).props('modelValue')).toBe(120)
    wrapper.unmount()
  })

  it('persists the expression, previews the backend timezone, and allows clearing it', async () => {
    vi.useFakeTimers()
    const { draft, previewCron, basic, wrapper } = setup({
      type: 'cron',
      expression: '0 9 * * *',
      timezone: null,
    })
    expect(basic.text()).toContain('运行机器本地时区（未指定）')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    expect(previewCron).toHaveBeenCalledWith('0 9 * * *', null, expect.any(AbortSignal))
    expect(basic.text()).toContain('每天 9:00')
    expect(basic.text()).toContain('实际采用时区：Asia/Shanghai')
    expect(basic.text()).toContain('下一次运行：')

    basic.findAllComponents(ElSelect)[1].vm.$emit('update:modelValue', 'Asia/Shanghai')
    await nextTick()
    await vi.advanceTimersByTimeAsync(300)
    expect(draft.value.schedule).toEqual({
      type: 'cron',
      expression: '0 9 * * *',
      timezone: 'Asia/Shanghai',
    })
    expect(previewCron).toHaveBeenLastCalledWith(
      '0 9 * * *',
      'Asia/Shanghai',
      expect.any(AbortSignal),
    )
    basic.findAllComponents(ElSelect)[1].vm.$emit('update:modelValue', '__machine_local__')
    await nextTick()
    expect(draft.value.schedule).toMatchObject({ timezone: null })
    wrapper.unmount()
  })

  it('shows preview errors and ignores a response from an earlier expression', async () => {
    vi.useFakeTimers()
    const { basic, previewCron, wrapper } = setup({
      type: 'cron',
      expression: '0 9 * * *',
      timezone: null,
    })
    let resolveFirst!: (value: {
      description: string
      timezone: string
      next_run_at: string
    }) => void
    previewCron.mockImplementationOnce(() => new Promise((resolve) => (resolveFirst = resolve)))
    await vi.advanceTimersByTimeAsync(300)
    basic.findAllComponents(ElInput).at(-1)!.vm.$emit('update:modelValue', '0 10 * * *')
    await nextTick()
    previewCron.mockRejectedValueOnce(new Error('无效 Cron 表达式'))
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    expect(basic.text()).toContain('预览失败：无效 Cron 表达式')
    resolveFirst({
      description: '旧结果',
      timezone: 'UTC',
      next_run_at: '2026-09-28T09:00:00Z',
    })
    await flushPromises()
    expect(basic.text()).not.toContain('旧结果')
    wrapper.unmount()
  })
})
