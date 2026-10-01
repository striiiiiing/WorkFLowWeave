import type { InjectionKey } from 'vue'
import { requireDependency } from '@/shared/lib/injection'
import type { AgentsApi } from './agentsApi'
export const agentsApiKey: InjectionKey<AgentsApi> = Symbol('agentsApi')
export const useAgentsApi = () => requireDependency(agentsApiKey, 'agentsApi')
