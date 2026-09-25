import type { CapabilityDescription, HealthReport } from './types'
import type { JsonObject } from '@/shared/types'

export interface PluginHealth {
  plugin: string
  kind: string
  capabilities: string[]
  status: string
  errors: string[]
  affectedResources: string[]
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
      affectedResources: [],
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
    addDiscoveryError(rows, details, diagnosticMessage(error.message))
  }
  const capabilityErrors = report?.error?.details.capability_errors ?? []
  if (!Array.isArray(capabilityErrors)) throw new Error('插件健康诊断格式无效')
  for (const error of capabilityErrors) {
    if (!error || typeof error !== 'object' || Array.isArray(error))
      throw new Error('插件健康诊断格式无效')
    const details = error.details
    if (!details || typeof details !== 'object' || Array.isArray(details))
      throw new Error('插件健康诊断缺少详情')
    addCapabilityError(rows, details, diagnosticMessage(error.message))
  }
  const reloadError = report?.error?.details.reload_error
  if (reloadError !== null && reloadError !== undefined) {
    if (!reloadError || typeof reloadError !== 'object' || Array.isArray(reloadError))
      throw new Error('插件健康诊断格式无效')
    const details = reloadError.details
    const message = diagnosticMessage(reloadError.message)
    const row = rows.get('系统/插件重载') ?? {
      plugin: '插件重载',
      kind: '系统',
      capabilities: [],
      status: '不可用',
      errors: [],
      affectedResources: [],
    }
    row.errors.push(message)
    if (details && typeof details === 'object' && !Array.isArray(details)) {
      const stage = details.stage
      if (typeof stage === 'string') row.errors[row.errors.length - 1] += `（阶段：${stage}）`
    }
    rows.set('系统/插件重载', row)
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
    affectedResources: [],
  }
  row.status = row.capabilities.length ? '部分降级' : '不可用'
  row.errors.push(message)
  rows.set(key, row)
}

function addCapabilityError(rows: Map<string, PluginHealth>, details: JsonObject, message: string) {
  if (typeof details.kind !== 'string' || typeof details.name !== 'string')
    throw new Error('插件健康诊断缺少能力标识')
  const kind = details.kind === 'source' ? 'collector' : details.kind
  const resources = details.resources ?? []
  if (!Array.isArray(resources) || resources.some((resource) => typeof resource !== 'string'))
    throw new Error('插件健康诊断的资源列表格式无效')
  const affected = resources.length ? `受影响资源：${resources.join('、')}` : ''
  const text = [message, affected].filter(Boolean).join('；')
  const matches = [...rows.values()].filter(
    (row) => row.kind === kind && row.capabilities.includes(details.name as string),
  )
  const targets =
    matches.length > 0
      ? matches
      : [
          {
            plugin: '未知插件',
            kind,
            capabilities: [details.name],
            status: '不可用',
            errors: [],
            affectedResources: [],
          },
        ]
  for (const row of targets) {
    row.status = matches.length ? '部分降级' : '不可用'
    row.errors.push(text)
    row.affectedResources.push(...(resources as string[]))
    if (!matches.length) rows.set(`${details.kind}/未知插件/${details.name}`, row)
  }
}

function diagnosticMessage(value: unknown): string {
  if (typeof value !== 'string') throw new Error('插件健康诊断缺少错误消息')
  return value
}
