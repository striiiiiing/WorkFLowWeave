import { useResourcesApi } from '../api/dependencies'
import type { MCPToolCatalog, MCPToolDescription } from '../api/resourcesApi'

export type { MCPToolCatalog, MCPToolDescription }

export function useResourceTransport() {
  return useResourcesApi()
}
