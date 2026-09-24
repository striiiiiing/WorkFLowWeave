import type { InjectionKey } from 'vue'
import { requireDependency } from '@/shared/lib/injection'
import type { SystemApi } from './systemApi'
export const systemApiKey: InjectionKey<SystemApi> = Symbol('systemApi')
export const useSystemApi = () => requireDependency(systemApiKey, 'systemApi')
