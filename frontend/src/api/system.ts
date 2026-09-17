import { request } from './client'
import type { CapabilityDescription, SystemHealth } from '@/types'

export const systemApi = {
  // 获取已注册插件能力描述
  getPlugins: () => request<CapabilityDescription[]>('/api/plugins'),

  // 系统健康状态
  getHealth: () => request<SystemHealth>('/api/system/health'),

  // 热重载插件与配置
  reloadSystem: () =>
    request<{ status: string }>('/api/system/reload', {
      method: 'POST',
    }),
}
