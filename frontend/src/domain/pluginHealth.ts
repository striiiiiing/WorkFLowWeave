import type { CapabilityDescription, HealthReport, JsonObject } from '@/types'

interface PluginHealth {
  plugin: string
  kind: string
  capabilities: string[]
  status: string
  errors: string[]
}

export function pluginHealthRows(plugins: CapabilityDescription[], health: HealthReport) {
  const rows = new Map<string, PluginHealth>()
  const report = health.components.find((item) => item.component === 'plugins')
  for (const capability of plugins) {
    const key = `${capability.kind}/${capability.plugin}`
    const row = rows.get(key) ?? {
      plugin: capability.plugin,
      kind: capability.kind,
      capabilities: [],
      status: report?.status === 'available' ? '已注册' : '待确认',
      errors: [],
    }
    row.capabilities.push(capability.name)
    rows.set(key, row)
  }
  const errors = report?.error?.details.discovery_errors ?? []
  if (!Array.isArray(errors)) throw new Error('插件健康诊断格式无效')
  for (const error of errors) {
    if (!error || typeof error !== 'object' || Array.isArray(error))
      throw new Error('插件健康诊断格式无效')
    const details = error.details
    if (!details || typeof details !== 'object' || Array.isArray(details))
      throw new Error('插件健康诊断缺少详情')
    addDiscoveryError(rows, details, String(error.message))
  }
  return [...rows.values()]
}

function addDiscoveryError(rows: Map<string, PluginHealth>, details: JsonObject, message: string) {
  if (typeof details.plugin !== 'string') throw new Error('插件健康诊断缺少插件标识')
  const kind = typeof details.kind === 'string' ? details.kind : '未知类型'
  const key = `${kind}/${details.plugin}`
  const row = rows.get(key) ?? {
    plugin: details.plugin,
    kind,
    capabilities: [],
    status: '不可用',
    errors: [],
  }
  row.status = row.capabilities.length ? '部分降级' : '不可用'
  row.errors.push(message)
  rows.set(key, row)
}
