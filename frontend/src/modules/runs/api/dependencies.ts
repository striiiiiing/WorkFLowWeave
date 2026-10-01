import type { InjectionKey } from 'vue'
import { requireDependency } from '@/shared/lib/injection'
import type { RunsApi } from './runsApi'
export const runsApiKey: InjectionKey<RunsApi> = Symbol('runsApi')
export const useRunsApi = () => requireDependency(runsApiKey, 'runsApi')
