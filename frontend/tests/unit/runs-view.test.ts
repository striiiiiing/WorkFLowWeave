import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { afterEach, expect, it, vi } from 'vitest'
import { runsApi } from '@/api/runs'
import RunsView from '@/views/RunsView.vue'
import type { SessionRecord } from '@/types'

vi.mock('@/api/runs', () => ({ runsApi: { list: vi.fn() } }))

const record: SessionRecord = {
  session_id: 'run_1',
  workflow_id: 'daily',
  workflow_name: '每日汇总',
  version: 1,
  status: 'completed',
  stage: 'finish',
  created_at: '2026-09-21T00:00:00Z',
  updated_at: '2026-09-21T00:00:00Z',
  finished_at: '2026-09-21T00:00:00Z',
  error: null,
  artifacts: [],
  snapshot_availability: 'available',
}
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => {
  wrappers.forEach((wrapper) => wrapper.unmount())
  wrappers.length = 0
  vi.clearAllMocks()
})
async function setup(rows = [record]) {
  vi.mocked(runsApi.list).mockResolvedValue(rows)
  const wrapper = mount(RunsView, {
    global: { plugins: [ElementPlus], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

it('renders historical names and distinguishes missing and unnamed records', async () => {
  const wrapper = await setup([
    record,
    { ...record, session_id: 'legacy', workflow_name: null },
    { ...record, session_id: 'unnamed', workflow_name: '' },
  ])
  for (const text of [
    '工作流名称',
    '工作流 ID',
    '每日汇总',
    'daily',
    '名称未记录',
    '未命名工作流',
  ]) {
    expect(wrapper.text()).toContain(text)
  }
})

it('filters by the selected field, resets paging, preserves submitted filters across pages, and resets', async () => {
  const wrapper = await setup(
    Array.from({ length: 20 }, (_, i) => ({ ...record, session_id: `run_${i}` })),
  )
  const button = (text: string) => wrapper.findAll('button').find((item) => item.text() === text)!
  await button('下一页').trigger('click')
  await flushPromises()
  expect(runsApi.list).toHaveBeenLastCalledWith({ limit: 20, offset: 20 }, expect.any(AbortSignal))
  await wrapper.get('input[aria-label="工作流名称"]').setValue('  每日  ')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(runsApi.list).toHaveBeenLastCalledWith(
    { workflow_name: '每日', limit: 20, offset: 0 },
    expect.any(AbortSignal),
  )
  await wrapper.get('input[aria-label="工作流名称"]').setValue('未提交草稿')
  await button('下一页').trigger('click')
  await flushPromises()
  expect(runsApi.list).toHaveBeenLastCalledWith(
    { workflow_name: '每日', limit: 20, offset: 20 },
    expect.any(AbortSignal),
  )

  for (const [field, label, value] of [
    ['workflow_id', '工作流 ID', 'daily'],
    ['session_id', 'Session ID', 'run_1'],
  ]) {
    wrapper.findAllComponents(ElSelect)[0].vm.$emit('update:modelValue', field)
    await flushPromises()
    expect(wrapper.get<HTMLInputElement>(`input[aria-label="${label}"]`).element.value).toBe('')
    await wrapper.get(`input[aria-label="${label}"]`).setValue(value)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(runsApi.list).toHaveBeenLastCalledWith(
      { [field]: value, limit: 20, offset: 0 },
      expect.any(AbortSignal),
    )
  }
  wrapper.findAllComponents(ElSelect)[0].vm.$emit('update:modelValue', 'status')
  await flushPromises()
  wrapper.findAllComponents(ElSelect)[1].vm.$emit('update:modelValue', 'failed')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(runsApi.list).toHaveBeenLastCalledWith(
    { status: 'failed', limit: 20, offset: 0 },
    expect.any(AbortSignal),
  )
  await button('重置').trigger('click')
  await flushPromises()
  expect(runsApi.list).toHaveBeenLastCalledWith({ limit: 20, offset: 0 }, expect.any(AbortSignal))
})

it('keeps failed queries visible as errors and supports retry', async () => {
  const wrapper = await setup()
  vi.mocked(runsApi.list).mockRejectedValueOnce(new Error('查询失败'))
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('查询失败')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  expect(wrapper.text()).toContain('每日汇总')
})
