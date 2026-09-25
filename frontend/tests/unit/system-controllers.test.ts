import { effectScope } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { useSystemDiagnostics } from '@/modules/system/composables/useSystemDiagnostics'
import { usePluginReload } from '@/modules/system/composables/usePluginReload'
import { pluginHealthRows } from '@/modules/system/model/pluginHealth'
import type { HealthReport } from '@/modules/system/model/types'
const healthy: HealthReport = {
  status: 'ready',
  accepting_runs: true,
  checked_at: '',
  components: [],
}
describe('independent system queries', () => {
  it('keeps valid health visible when plugin projection is malformed and can retry that source', async () => {
    const health = {
      ...healthy,
      components: [
        {
          component: 'plugins',
          status: 'degraded',
          required: false,
          checked_at: null,
          error: {
            code: 'bad',
            message: 'bad diagnostics',
            details: { discovery_errors: 'malformed' },
          },
        },
      ],
    }
    const api = {
      plugins: vi.fn().mockResolvedValue([]),
      health: vi.fn().mockResolvedValue(health),
    }
    const scope = effectScope()
    const diagnostics = scope.run(() => useSystemDiagnostics(api))!
    await flushPromises()
    expect(diagnostics.health.data.value?.status).toBe('ready')
    expect(diagnostics.plugins.error.value).toBe('')
    expect(diagnostics.projection.value.error).toContain('格式无效')
    expect(diagnostics.projection.value.rows).toBeUndefined()
    api.health.mockResolvedValue(healthy)
    await diagnostics.health.refresh()
    expect(diagnostics.projection.value.error).toBe('')
    expect(api.plugins).toHaveBeenCalledTimes(1)
    scope.stop()
  })
  it('reports reload diagnostics separately, refreshes both sources once, and never retries a failed write', async () => {
    const api = {
      plugins: vi.fn().mockResolvedValue([]),
      health: vi.fn().mockResolvedValue(healthy),
      reload: vi.fn().mockResolvedValue({
        scope: 'plugins',
        report: {
          registered: [],
          errors: [{ code: 'plugin_failure', message: '插件不可用', details: {} }],
        },
      }),
    }
    const scope = effectScope()
    const { diagnostics, action } = scope.run(() => {
      const diagnostics = useSystemDiagnostics(api)
      return { diagnostics, action: usePluginReload(diagnostics.refresh, api) }
    })!
    await flushPromises()
    const result = await action.reload()
    expect(result.status).toBe('success')
    expect(action.report.value?.errors[0].message).toBe('插件不可用')
    expect(api.plugins).toHaveBeenCalledTimes(2)
    expect(api.health).toHaveBeenCalledTimes(2)
    api.reload.mockRejectedValue(new Error('重载网络错误'))
    await action.reload()
    expect(action.error.value).toBe('重载网络错误')
    expect(action.report.value).toBeUndefined()
    expect(diagnostics.health.data.value?.status).toBe('ready')
    expect(api.reload).toHaveBeenCalledTimes(2)
    expect(api.health).toHaveBeenCalledTimes(2)
    scope.stop()
  })
})

it('rejects malformed diagnostic messages instead of presenting an invented fallback', () => {
  const report: HealthReport = {
    ...healthy,
    components: [
      {
        component: 'plugins',
        status: 'degraded',
        required: false,
        checked_at: null,
        error: {
          code: 'bad',
          message: 'bad',
          details: { discovery_errors: [{ details: { plugin: 'broken' } }] },
        },
      },
    ],
  }
  expect(() => pluginHealthRows([], report)).toThrow('缺少错误消息')
})
