import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import DashboardView from '@/views/DashboardView.vue'
import RunsView from '@/views/RunsView.vue'
import SessionTable from '@/components/common/SessionTable.vue'
import { pluginHealthRows } from '@/domain/pluginHealth'
import { workflowsApi } from '@/api/workflows'
import { runsApi } from '@/api/runs'
import type { CapabilityDescription, HealthReport, SessionRecord } from '@/types'

const { health, plugins } = vi.hoisted(() => ({ health: vi.fn(), plugins: vi.fn() }))
vi.mock('@/api/system', () => ({ systemApi: { health, plugins } }))
vi.mock('@/api/workflows', () => ({ workflowsApi: { list: vi.fn() } }))
vi.mock('@/api/runs', () => ({ runsApi: { list: vi.fn() } }))

const capability: CapabilityDescription = {
  kind: 'collector',
  name: 'logs',
  plugin: 'builtin',
  description: '日志采集',
  capabilities: [],
  options_schema: {},
  setters_schema: null,
  fields: [],
  count_unit: null,
}
const healthReport: HealthReport = {
  status: 'ready',
  accepting_runs: true,
  checked_at: '2026-09-21T00:00:00Z',
  components: [
    {
      component: 'plugins',
      status: 'degraded',
      required: false,
      checked_at: '2026-09-21T00:00:00Z',
      error: {
        code: 'plugin_degraded',
        message: '可选插件存在诊断',
        details: {
          discovery_errors: [],
          capability_errors: [
            {
              code: 'capability_missing',
              message: '已保存资源引用的插件能力不可用',
              details: { kind: 'source', name: 'logs', resources: ['source-a'] },
            },
          ],
          reload_error: null,
        },
      },
    },
  ],
}
const session: SessionRecord = {
  session_id: 'run-1',
  workflow_id: 'daily',
  workflow_name: '每日汇总',
  version: 1,
  status: 'completed',
  stage: 'aggregate',
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

describe('monitoring diagnostics', () => {
  it('keeps capability impact and affected resource details', () => {
    const rows = pluginHealthRows([capability], healthReport)
    expect(rows[0]).toMatchObject({
      status: '部分降级',
      errors: ['已保存资源引用的插件能力不可用；受影响资源：source-a'],
      affectedResources: ['source-a'],
    })
  })

  it('keeps system health visible when the plugin list query fails', async () => {
    vi.mocked(workflowsApi.list).mockResolvedValue([])
    vi.mocked(runsApi.list).mockResolvedValue([])
    health.mockResolvedValue({ ...healthReport, status: 'ready', components: [] })
    plugins.mockRejectedValue(new Error('插件目录读取失败'))
    const wrapper = mount(DashboardView, {
      global: { plugins: [ElementPlus], stubs: { RouterLink: true } },
    })
    wrappers.push(wrapper)
    await flushPromises()
    expect(wrapper.text()).toContain('系统状态')
    expect(wrapper.text()).toContain('就绪')
    expect(wrapper.text()).toContain('插件目录读取失败')
    expect(wrapper.text()).not.toContain('系统状态—')
  })

  it('shows readable mobile record details and Chinese stage names', () => {
    const wrapper = mount(SessionTable, {
      props: { sessions: [session] },
      global: {
        plugins: [ElementPlus],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    wrappers.push(wrapper)
    expect(wrapper.text()).toContain('每日汇总')
    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).toContain('汇聚汇总')
    expect(wrapper.text()).toContain('查看详情')
  })

  it('submits after and before as timezone-bearing instants with field filters', async () => {
    vi.mocked(runsApi.list).mockResolvedValue([session])
    const wrapper = mount(RunsView, {
      global: { plugins: [ElementPlus], stubs: { RouterLink: true } },
    })
    wrappers.push(wrapper)
    await flushPromises()
    await wrapper.get('input[aria-label="工作流名称"]').setValue('每日')
    await wrapper.get('input[aria-label="开始时间"]').setValue('2026-09-20T08:00')
    await wrapper.get('input[aria-label="结束时间"]').setValue('2026-09-21T08:00')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const call = vi.mocked(runsApi.list).mock.calls.at(-1)
    expect(call?.[0]).toMatchObject({
      workflow_name: '每日',
      after: new Date('2026-09-20T08:00').toISOString(),
      before: new Date('2026-09-21T08:00').toISOString(),
      limit: 20,
      offset: 0,
    })
  })
})
