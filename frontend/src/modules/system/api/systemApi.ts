import { isErrorInfo, type HttpClient } from '@/shared/api'
import type { CapabilityDescription, DiscoveryReport, HealthReport } from '../model/types'

function isHealthReport(value: unknown): value is HealthReport {
  if (!value || typeof value !== 'object') return false
  const report = value as Partial<HealthReport>
  return (
    ['ready', 'degraded', 'unavailable'].includes(String(report.status)) &&
    typeof report.accepting_runs === 'boolean' &&
    typeof report.checked_at === 'string' &&
    Array.isArray(report.components) &&
    report.components.every(
      (item) =>
        item &&
        typeof item === 'object' &&
        typeof item.component === 'string' &&
        ['available', 'degraded', 'unavailable', 'unknown'].includes(item.status) &&
        typeof item.required === 'boolean' &&
        (item.checked_at === null || typeof item.checked_at === 'string') &&
        (item.error === null || isErrorInfo(item.error)),
    )
  )
}

export function createSystemApi(http: HttpClient) {
  return {
    // Health is a report even when the service deliberately answers 503.
    health: (signal?: AbortSignal) =>
      http.request<HealthReport>({
        url: '/health',
        signal,
        acceptResponse: (status, body) => status === 503 && isHealthReport(body),
      }),
    plugins: (signal?: AbortSignal) =>
      http.request<CapabilityDescription[]>({ url: '/plugins', signal }),
    reload: (scope: 'resources' | 'plugins') =>
      http.request<{ scope: string; report: DiscoveryReport | null }>({
        url: '/reload',
        method: 'POST',
        params: { scope },
      }),
  }
}
export type SystemApi = ReturnType<typeof createSystemApi>
