import { segment, type HttpClient } from '@/shared/api'
import type {
  Credential,
  ResourceKind,
  ResourceMap,
  SourceConfig,
  SourceOverride,
  AIConfig,
} from '../model/types'

export function createResourcesApi(http: HttpClient) {
  return {
    resolveSource: (id: string, override?: SourceOverride, signal?: AbortSignal) =>
      http.request<SourceConfig>({
        url: `/sources/${segment(id)}/resolve`,
        method: 'POST',
        data: override ?? {},
        signal,
      }),
    discoverAIModels: (config: AIConfig) =>
      http.request<string[]>({
        url: '/ai/discover-models',
        method: 'POST',
        data: config,
      }),
    protectCredential: (plaintext: string) =>
      http.request<Extract<Credential, { kind: 'encrypted' }>>({
        url: '/credentials/protect',
        method: 'POST',
        data: { plaintext },
      }),
    list: <K extends ResourceKind>(kind: K, signal?: AbortSignal) =>
      http.request<ResourceMap[K][]>({ url: `/${kind}`, signal }),
    get: <K extends ResourceKind>(kind: K, id: string, signal?: AbortSignal) =>
      http.request<ResourceMap[K]>({ url: `/${kind}/${segment(id)}`, signal }),
    create: <K extends ResourceKind>(kind: K, value: ResourceMap[K]) =>
      http.request<ResourceMap[K]>({ url: `/${kind}`, method: 'POST', data: value }),
    replace: <K extends ResourceKind>(kind: K, id: string, value: ResourceMap[K]) =>
      http.request<ResourceMap[K]>({ url: `/${kind}/${segment(id)}`, method: 'PUT', data: value }),
    delete: (kind: ResourceKind, id: string) =>
      http.request<void>({ url: `/${kind}/${segment(id)}`, method: 'DELETE' }),
  }
}
export type ResourcesApi = ReturnType<typeof createResourcesApi>
