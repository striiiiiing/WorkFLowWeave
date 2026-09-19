import { request, segment } from './client'
import type { ResourceKind, ResourceMap } from '@/types'

export const resourcesApi = {
  list: <K extends ResourceKind>(kind: K, signal?: AbortSignal) =>
    request<ResourceMap[K][]>(`/${kind}`, { signal }),
  get: <K extends ResourceKind>(kind: K, id: string, signal?: AbortSignal) =>
    request<ResourceMap[K]>(`/${kind}/${segment(id)}`, { signal }),
  create: <K extends ResourceKind>(kind: K, value: ResourceMap[K]) =>
    request<ResourceMap[K]>(`/${kind}`, { method: 'POST', body: JSON.stringify(value) }),
  replace: <K extends ResourceKind>(kind: K, id: string, value: ResourceMap[K]) =>
    request<ResourceMap[K]>(`/${kind}/${segment(id)}`, {
      method: 'PUT',
      body: JSON.stringify(value),
    }),
  delete: (kind: ResourceKind, id: string) =>
    request<void>(`/${kind}/${segment(id)}`, { method: 'DELETE' }),
}
