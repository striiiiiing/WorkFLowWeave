import { defineComponent, nextTick, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, {
  ElDatePicker,
  ElForm,
  ElInput,
  ElInputNumber,
  ElOption,
  ElSelect,
} from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import WorkflowBasicInfo from '@/modules/workflows/ui/WorkflowBasicInfo.vue'
import { workflowsApiKey } from '@/modules/workflows/api/dependencies'
import { parseCronPreset } from '@/modules/workflows/model/cronPresets'
import { createWorkflow, type WorkflowSchedule } from '@/modules/workflows/public'

function setup(schedule?: WorkflowSchedule | null) {
  const draft = ref({ ...createWorkflow(), ...(schedule === undefined ? {} : { schedule }) })
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
  it('edits a one-time instant and generates hourly, daily and weekly cron expressions', async () => {
    const { draft, basic, wrapper } = setup()
    expect(draft.value.schedule).toEqual({ type: 'cron', expression: '0 9 * * *', timezone: null })
    expect(basic.findAllComponents(ElSelect)[0].props('modelValue')).toBe('daily')
    expect(basic.findAllComponents(ElSelect)).toHaveLength(1)
    expect(basic.text()).toContain('运行机器本地时区（不指定）')
    expect(basic.findAllComponents(ElOption).map((option) => option.props('value'))).toEqual([
      'manual',
      'at',
      'hourly',
      'daily',
      'weekly',
      'custom',
    ])
    expect(
      basic
        .findAllComponents(ElOption)
        .find((option) => option.props('value') === 'at')
        ?.props('label'),
    ).toBe('单次运行')
    basic.findAllComponents(ElSelect)[0].vm.$emit('update:modelValue', 'manual')
    await nextTick()
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

    basic.findAllComponents(ElSelect)[0].vm.$emit('update:modelValue', 'hourly')
    await nextTick()
    expect(draft.value.schedule).toEqual({ type: 'cron', expression: '0 * * * *', timezone: null })
    basic.getComponent(ElInputNumber).vm.$emit('update:modelValue', 15)
    await nextTick()
    expect(draft.value.schedule).toMatchObject({ expression: '15 * * * *' })

    basic.findAllComponents(ElSelect)[0].vm.$emit('update:modelValue', 'daily')
    await nextTick()
    expect(draft.value.schedule).toMatchObject({ expression: '0 9 * * *' })
    const timeInput = () =>
      basic.findAllComponents(ElInput).find((input) => input.props('type') === 'time')!
    expect(timeInput().props('modelValue')).toBe('09:00')
    timeInput().vm.$emit('update:modelValue', '18:30')
    await nextTick()
    expect(draft.value.schedule).toMatchObject({ expression: '30 18 * * *' })

    basic.findAllComponents(ElSelect)[0].vm.$emit('update:modelValue', 'weekly')
    await nextTick()
    expect(draft.value.schedule).toMatchObject({ expression: '0 9 * * MON' })
    basic.findAllComponents(ElSelect)[1].vm.$emit('update:modelValue', 'FRI')
    await nextTick()
    timeInput().vm.$emit('update:modelValue', '10:45')
    await nextTick()
    expect(draft.value.schedule).toEqual({
      type: 'cron',
      expression: '45 10 * * FRI',
      timezone: null,
    })
    wrapper.unmount()
  })

  it('keeps an existing interval read-only until the user chooses a new plan', async () => {
    const { draft, basic, wrapper } = setup({ type: 'every', every_seconds: 120 })
    expect(basic.findAllComponents(ElSelect)[0].props('modelValue')).toBe('every')
    expect(basic.text()).toContain('每 120 秒运行（只读）')
    expect(basic.findAllComponents(ElInputNumber)).toHaveLength(0)
    expect(draft.value.schedule).toEqual({ type: 'every', every_seconds: 120 })
    basic.findAllComponents(ElSelect)[0].vm.$emit('update:modelValue', 'daily')
    await nextTick()
    expect(draft.value.schedule).toEqual({ type: 'cron', expression: '0 9 * * *', timezone: null })
    wrapper.unmount()
  })

  it('previews the machine timezone without a timezone selector', async () => {
    vi.useFakeTimers()
    const { previewCron, basic, wrapper } = setup()
    expect(basic.text()).toContain('运行机器本地时区（不指定）')
    expect(basic.findAllComponents(ElSelect)[0].props('modelValue')).toBe('daily')
    expect(basic.findAllComponents(ElSelect)).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    expect(previewCron).toHaveBeenCalledWith('0 9 * * *', null, expect.any(AbortSignal))
    expect(basic.text()).toContain('每天 9:00')
    expect(basic.text()).toContain('实际采用时区：Asia/Shanghai')
    expect(basic.text()).toContain('下一次运行：')
    wrapper.unmount()
  })

  it('preserves an existing explicit timezone until the schedule changes', async () => {
    vi.useFakeTimers()
    const { draft, previewCron, basic, wrapper } = setup({
      type: 'cron',
      expression: '0 9 * * *',
      timezone: 'UTC',
    })
    expect(basic.text()).toContain('原有计划时区：UTC（只读')
    expect(basic.findAllComponents(ElSelect)).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(300)
    expect(previewCron).toHaveBeenCalledWith('0 9 * * *', 'UTC', expect.any(AbortSignal))
    basic.findAllComponents(ElInput)[1].vm.$emit('update:modelValue', '新名称')
    await nextTick()
    expect(draft.value.schedule).toMatchObject({ timezone: 'UTC' })
    basic
      .findAllComponents(ElInput)
      .find((input) => input.props('type') === 'time')!
      .vm.$emit('update:modelValue', '10:00')
    await nextTick()
    expect(draft.value.schedule).toEqual({ type: 'cron', expression: '0 10 * * *', timezone: null })
    await vi.advanceTimersByTimeAsync(300)
    expect(previewCron).toHaveBeenLastCalledWith('0 10 * * *', null, expect.any(AbortSignal))
    wrapper.unmount()
  })

  it('keeps custom cron expressions editable and ignores stale preview responses', async () => {
    vi.useFakeTimers()
    const { basic, draft, previewCron, wrapper } = setup({
      type: 'cron',
      expression: '*/15 9-17 * * MON-FRI',
      timezone: null,
    })
    expect(basic.findAllComponents(ElSelect)[0].props('modelValue')).toBe('custom')
    let resolveFirst!: (value: {
      description: string
      timezone: string
      next_run_at: string
    }) => void
    previewCron.mockImplementationOnce(() => new Promise((resolve) => (resolveFirst = resolve)))
    await vi.advanceTimersByTimeAsync(300)
    basic.findAllComponents(ElInput).at(-1)!.vm.$emit('update:modelValue', '0 10 * * *')
    await nextTick()
    expect(draft.value.schedule).toMatchObject({ expression: '0 10 * * *' })
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
    expect(basic.findAllComponents(ElSelect)[0].props('modelValue')).toBe('custom')
    wrapper.unmount()
  })

  it('recognizes only supported presets and leaves other cron syntax custom', () => {
    expect(parseCronPreset('15 * * * *')).toEqual({ mode: 'hourly', minute: 15 })
    expect(parseCronPreset('30 18 * * *')).toEqual({ mode: 'daily', hour: 18, minute: 30 })
    expect(parseCronPreset('45 10 * * FRI')).toEqual({
      mode: 'weekly',
      day: 'FRI',
      hour: 10,
      minute: 45,
    })
    expect(parseCronPreset('*/15 9-17 * * MON-FRI')).toEqual({ mode: 'custom' })
  })
})
