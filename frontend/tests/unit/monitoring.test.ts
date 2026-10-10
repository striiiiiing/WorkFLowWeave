import { systemApiKey } from '@/modules/system/public'
import { workflowsApiKey } from '@/modules/workflows/public'
import { routerKey } from 'vue-router'
import { runsApiKey } from '@/modules/runs/public'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import DashboardView from '@/pages/dashboard/DashboardPage.vue'
import RunsView from '@/pages/runs/RunListPage.vue'
import { SessionTable } from '@/modules/runs/public'
import { pluginHealthRows } from '@/modules/system/public'
import { workflowsApi } from '@/app/services'
import { runsApi } from '@/app/services'
import type { SessionRecord } from '@/modules/runs/public'
import type { CapabilityDescription, HealthReport } from '@/modules/system/public'

const { health, plugins } = vi.hoisted(() => ({ health: vi.fn(), plugins: vi.fn() }))
vi.mock('@/app/services', () => ({
  systemApi: { health, plugins },
  workflowsApi: { list: vi.fn() },
  runsApi: { list: vi.fn() },
}))

const capability: CapabilityDescription = {
  kind: 'channel',
  name: 'email',
  plugin: 'builtin',
  description: '邮件渠道',
  capabilities: [],
  options_schema: {},
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
              details: { kind: 'channel', name: 'email', resources: ['source-a'] },
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

  it('keeps system health visible without loading the plugin list', async () => {
    vi.mocked(workflowsApi.list).mockResolvedValue([])
    vi.mocked(runsApi.list).mockResolvedValue([])
    health.mockResolvedValue({ ...healthReport, status: 'ready', components: [] })
    plugins.mockRejectedValue(new Error('插件目录读取失败'))
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
    wrappers.push(wrapper)
    await flushPromises()
    expect(wrapper.text()).toContain('系统状态')
    expect(wrapper.text()).toContain('就绪')
    expect(wrapper.text()).not.toContain('插件目录读取失败')
    expect(wrapper.text()).not.toContain('系统状态—')
    expect(plugins).not.toHaveBeenCalled()
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

it('reads one health result for dashboard consumers and retains prior counts on refresh failure', async () => {
  vi.mocked(workflowsApi.list).mockResolvedValue([])
  vi.mocked(runsApi.list).mockResolvedValue([session])
  health.mockResolvedValue(healthReport)
  plugins.mockResolvedValue([capability])
  const wrapper = mount(DashboardView, {
    global: {
      plugins: [ElementPlus],
      provide: {
        [runsApiKey as symbol]: runsApi,
        [workflowsApiKey as symbol]: workflowsApi,
        [systemApiKey as symbol]: { health, plugins },
        [routerKey as symbol]: { push: vi.fn() },
      },
    },
  })
  wrappers.push(wrapper)
  await flushPromises()
  expect(health).toHaveBeenCalledTimes(1)
  expect(plugins).not.toHaveBeenCalled()
  expect(runsApi.list).toHaveBeenCalledWith({ limit: 5 }, expect.any(AbortSignal))
  vi.mocked(workflowsApi.list).mockRejectedValue(new Error('刷新工作流失败'))
  await wrapper
    .findAll('button')
    .find((button) => button.text() === '刷新')!
    .trigger('click')
  await flushPromises()
  expect(health).toHaveBeenCalledTimes(2)
  const card = wrapper.findAll('.el-card').find((card) => card.text().includes('已保存工作流'))!
  expect(card.get('.text-3xl').text()).toBe('0')
  expect(card.text()).toContain('以下内容来自上次成功读取')
  expect(wrapper.text()).toContain('每日汇总')
})
