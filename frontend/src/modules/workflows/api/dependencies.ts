import type { InjectionKey } from 'vue'
import { requireDependency } from '@/shared/lib/injection'
import type { WorkflowsApi } from './workflowsApi'
export const workflowsApiKey: InjectionKey<WorkflowsApi> = Symbol('workflowsApi')
export const useWorkflowsApi = () => requireDependency(workflowsApiKey, 'workflowsApi')
