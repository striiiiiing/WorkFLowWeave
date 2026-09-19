import { request } from './client'
import type { CapabilityDescription, DiscoveryReport, HealthReport } from '@/types'

export const systemApi = {
  // Health is a report even when the service deliberately answers 503.
  health: (signal?: AbortSignal) => request<HealthReport>('/health', { signal }, [503]),
  plugins: (signal?: AbortSignal) => request<CapabilityDescription[]>('/plugins', { signal }),
  reload: (scope: 'resources' | 'plugins') =>
    request<{ scope: string; report: DiscoveryReport | null }>(`/reload?scope=${scope}`, {
      method: 'POST',
    }),
}
