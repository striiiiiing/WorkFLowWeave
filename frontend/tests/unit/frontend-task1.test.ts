import { defineComponent, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { expect, it, vi } from 'vitest'
import { pluginHealthRows } from '@/domain/pluginHealth'
import { createFanIn, createWorkflow } from '@/domain/workflow'
import SourceStepCard from '@/components/workflow/SourceStepCard.vue'
import FanInCard from '@/components/workflow/FanInCard.vue'
import DashboardView from '@/views/DashboardView.vue'
import { resourcesApi } from '@/api/resources'
import { runsApi } from '@/api/runs'
import type { CapabilityDescription, HealthReport } from '@/types'
const { health, plugins } = vi.hoisted(() => ({ health: vi.fn(), plugins: vi.fn() }))
vi.mock('@/api/system', () => ({ systemApi: { health, plugins } }))
vi.mock('@/api/resources', () => ({ resourcesApi: { list: vi.fn().mockResolvedValue([]) } }))
vi.mock('@/api/runs', () => ({ runsApi: { list: vi.fn().mockResolvedValue([]) } }))
const capability = (kind: 'collector' | 'channel', name: string): CapabilityDescription => ({
  kind,
  name,
  plugin: 'example',
  description: '',
  capabilities: [],
  options_schema: {},
  setters_schema: null,
  fields: [],
  count_unit: null,
})
const report = (): HealthReport => ({
  status: 'ready',
  accepting_runs: true,
  checked_at: '',
  components: [
    {
      component: 'resource_store',
      status: 'available',
      required: true,
      error: null,
      checked_at: null,
    },
    { component: 'plugins', status: 'available', required: false, error: null, checked_at: null },
  ],
})
it('groups plugin capabilities and reports failed discovery without claiming connectivity', () => {
  const value = report()
  value.components[1].status = 'degraded'
  value.components[1].error = {
    code: 'plugin_degraded',
    message: '诊断',
    details: {
      discovery_errors: [
        {
          code: 'plugin_discovery_failed',
          message: '注册失败',
          details: { plugin: 'broken', kind: 'collector' },
        },
      ],
    },
  }
  const rows = pluginHealthRows(
    [
      capability('collector', 'one'),
      capability('collector', 'two'),
      capability('channel', 'notify'),
    ],
    value,
  )
  expect(rows).toHaveLength(3)
  expect(rows[0]).toMatchObject({ capabilities: ['one', 'two'], status: '待确认' })
  expect(rows[1]).toMatchObject({ kind: 'channel', capabilities: ['notify'] })
  expect(rows[2]).toMatchObject({ plugin: 'broken', status: '不可用', errors: ['注册失败'] })
  expect(pluginHealthRows([capability('collector', 'one')], report())[0].status).toBe('已注册')
  expect(
    pluginHealthRows([capability('collector', 'one')], { ...report(), components: [] })[0].status,
  ).toBe('待确认')
})
it('shows internal monitoring only in dashboard advanced mode', async () => {
  vi.mocked(resourcesApi.list).mockResolvedValue([])
  vi.mocked(runsApi.list).mockResolvedValue([])
  health.mockResolvedValue(report())
  plugins.mockResolvedValue([capability('collector', 'one')])
  const wrapper = mount(DashboardView, {
    global: { plugins: [ElementPlus], stubs: { RouterLink: true } },
  })
  await flushPromises()
  expect(wrapper.text()).toContain('插件健康状态')
  expect(wrapper.text()).toContain('example')
  expect(wrapper.text()).not.toContain('resource_store')
  await wrapper.get('[role="switch"]').trigger('click')
  expect(wrapper.text()).toContain('resource_store')
  await wrapper.get('[role="switch"]').trigger('click')
  expect(wrapper.text()).not.toContain('resource_store')
  wrapper.unmount()
})
it('hides the four workflow options and preserves edited values across mode changes', async () => {
  plugins.mockResolvedValue([])
  const workflow = ref({
    ...createWorkflow(),
    on_all_empty: 'notice' as const,
    input_separator: 'source-separator',
    fan_in: { ...createFanIn(), separator: 'result-separator', mark_incomplete: false },
  })
  const advanced = ref(false)
  const wrapper = mount(
    defineComponent({
      components: { SourceStepCard, FanInCard },
      setup: () => ({ workflow, advanced }),
      template:
        '<el-form :model="workflow"><SourceStepCard v-model="workflow" :sources="[]" :advanced="advanced" /><FanInCard v-model="workflow" :configs="[]" :advanced="advanced" /></el-form>',
    }),
    { global: { plugins: [ElementPlus] } },
  )
  await flushPromises()
  const labels = ['全部为空时', '分隔符', '标记不完整结果']
  for (const label of labels) expect(wrapper.text()).not.toContain(label)
  advanced.value = true
  await flushPromises()
  for (const label of labels) expect(wrapper.text()).toContain(label)
  const inputs = wrapper.findAll('textarea')
  await inputs[0].setValue('edited-source')
  await inputs[1].setValue('edited-result')
  advanced.value = false
  await flushPromises()
  for (const label of labels) expect(wrapper.text()).not.toContain(label)
  expect(workflow.value).toMatchObject({
    on_all_empty: 'notice',
    input_separator: 'edited-source',
    fan_in: { separator: 'edited-result', mark_incomplete: false },
  })
  advanced.value = true
  await flushPromises()
  expect(wrapper.findAll('textarea').map((input) => input.element.value)).toEqual([
    'edited-source',
    'edited-result',
  ])
  wrapper.unmount()
})
