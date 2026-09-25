import { computed } from 'vue'
import { useSystemApi } from '../api/dependencies'
import type { SystemApi } from '../api/systemApi'
import { pluginHealthRows } from '../model/pluginHealth'
import { useCapabilities } from './useCapabilities'
import { useSystemHealth } from './useSystemHealth'
export function useSystemDiagnostics(api: Pick<SystemApi, 'plugins' | 'health'> = useSystemApi()) {
  const plugins = useCapabilities(api)
  const health = useSystemHealth(api)
  const projection = computed(() => {
    if (!plugins.data.value || !health.data.value) return { rows: undefined, error: '' }
    try {
      return { rows: pluginHealthRows(plugins.data.value, health.data.value), error: '' }
    } catch (cause) {
      return { rows: undefined, error: cause instanceof Error ? cause.message : String(cause) }
    }
  })
  async function refresh() {
    await Promise.all([plugins.refresh(), health.refresh()])
  }
  return { plugins, health, projection, refresh }
}
export type SystemDiagnostics = ReturnType<typeof useSystemDiagnostics>
