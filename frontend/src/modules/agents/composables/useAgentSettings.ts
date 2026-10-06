import { useQuery } from '@/shared/async/useQuery'
import { isTaskSuccess, useAsyncTask } from '@/shared/async/useAsyncTask'
import type { AgentsApi } from '../api/agentsApi'
import type { AgentConfig } from '../model/public'
import { saveDefaultAgentModel } from './agentModels'

export function useAgentSettings(api: Pick<AgentsApi, 'config' | 'updateConfig' | 'updateTool'>) {
  const query = useQuery((signal) => api.config(signal))
  const action = useAsyncTask()
  const toolsAction = useAsyncTask()

  async function save(config: AgentConfig, defaultModel: string) {
    const models = query.data.value?.models ?? []
    if (defaultModel && !models.some((item) => item.reference === defaultModel)) {
      action.error.value = '默认模型已不可用，请重新选择供应商渠道模型'
      return false
    }
    const result = await action.run(() => api.updateConfig(config))
    if (!isTaskSuccess(result)) return false
    try {
      saveDefaultAgentModel(defaultModel)
    } catch {
      action.error.value = '服务端设置已保存，但浏览器默认模型保存失败，请检查浏览器存储权限后重试'
      await query.refresh()
      return false
    }
    await query.refresh()
    return !query.error.value
  }

  async function toggleTool(plugin: string, enabled: boolean) {
    const result = await toolsAction.run(() => api.updateTool(plugin, enabled))
    if (!isTaskSuccess(result)) return false
    await query.refresh()
    return !query.error.value
  }

  return { query, action, toolsAction, save, toggleTool }
}
