import type { InjectionKey } from 'vue'
import { requireDependency } from '@/shared/lib/injection'
import type { ResourcesApi } from './resourcesApi'
export const resourcesApiKey: InjectionKey<ResourcesApi> = Symbol('resourcesApi')
export const useResourcesApi = () => requireDependency(resourcesApiKey, 'resourcesApi')
