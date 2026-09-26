import { runsApiKey } from '@/modules/runs/public'
import { systemApiKey } from '@/modules/system/public'
import { workflowsApiKey } from '@/modules/workflows/public'
import { routerKey } from 'vue-router'
import { defineComponent, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { expect, it, vi } from 'vitest'
import { pluginHealthRows } from '@/modules/system/public'
import { createFanIn, createWorkflow, useWorkflowEditor } from '@/modules/workflows/public'
import SourceStepCard from '@/modules/workflows/ui/SourceStepCard.vue'
import FanInCard from '@/modules/workflows/ui/FanInCard.vue'
import DashboardView from '@/pages/dashboard/DashboardPage.vue'
import { workflowsApi } from '@/app/services'
import { runsApi } from '@/app/services'
import type { CapabilityDescription, HealthReport } from '@/shared/types'
const { health, plugins } = vi.hoisted(() => ({ health: vi.fn(), plugins: vi.fn() }))
vi.mock('@/app/services', () => ({
  systemApi: { health, plugins },
  workflowsApi: { list: vi.fn().mockResolvedValue([]) },
  runsApi: { list: vi.fn().mockResolvedValue([]) },
}))
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
it('keeps the dashboard focused on system health and recent runs', async () => {
  vi.mocked(workflowsApi.list).mockResolvedValue([])
  vi.mocked(runsApi.list).mockResolvedValue([])
  health.mockResolvedValue(report())
  plugins.mockResolvedValue([capability('collector', 'one')])
  const wrapper = mount(DashboardView, {
    global: {
      provide: {
        [runsApiKey as symbol]: runsApi,
        [workflowsApiKey as symbol]: workflowsApi,
        [systemApiKey as symbol]: { health, plugins },
        [routerKey as symbol]: { push: vi.fn() },
      },
      plugins: [ElementPlus],
      stubs: { RouterLink: true },
    },
  })
  await flushPromises()
  expect(wrapper.text()).toContain('系统状态')
  expect(wrapper.text()).not.toContain('插件健康状态')
  expect(wrapper.text()).not.toContain('resource_store')
  expect(plugins).not.toHaveBeenCalled()
  expect(wrapper.find('[role="switch"]').exists()).toBe(false)
  wrapper.unmount()
})
it('hides the four workflow options and preserves edited values across mode changes', async () => {
  plugins.mockResolvedValue([])
  const initial = {
    ...createWorkflow(),
    on_all_empty: 'notice' as const,
    input_separator: 'source-separator',
    fan_in: { ...createFanIn(), separator: 'result-separator', mark_incomplete: false },
  }
  const advanced = ref(false)
  let editor!: ReturnType<typeof useWorkflowEditor>
  const wrapper = mount(
    defineComponent({
      components: { SourceStepCard, FanInCard },
      setup: () => {
        editor = useWorkflowEditor({ identity: undefined })
        editor.replace(initial)
        return { editor, advanced }
      },
      template:
        '<el-form :model="editor.draft"><SourceStepCard :editor="editor" :sources="[]" :gateway="gateway" :capabilities="[]" :protect="protect" :advanced="advanced" /><FanInCard :editor="editor" :configs="[]" :advanced="advanced" /></el-form>',
    }),
    {
      global: {
        plugins: [ElementPlus],
        mocks: { gateway: { resolve: vi.fn(), save: vi.fn() }, protect: vi.fn() },
      },
    },
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
  expect(editor.draft.value).toMatchObject({
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
