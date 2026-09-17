import { request } from './client'
import type {
  SourceConfig,
  SetterTemplate,
  AIConfig,
  ChannelConfig,
  Credential,
  WorkflowDefinition,
  ID,
} from '@/types'

export const resourcesApi = {
  // 采集源
  listSources: () => request<SourceConfig[]>('/api/resources/sources'),
  getSource: (id: ID) => request<SourceConfig>(`/api/resources/sources/${id}`),
  saveSource: (source: SourceConfig) =>
    request<SourceConfig>('/api/resources/sources', {
      method: 'POST',
      body: JSON.stringify(source),
    }),
  deleteSource: (id: ID) =>
    request<void>(`/api/resources/sources/${id}`, { method: 'DELETE' }),

  // Setter 模板
  listSetterTemplates: () => request<SetterTemplate[]>('/api/resources/setter-templates'),
  saveSetterTemplate: (template: SetterTemplate) =>
    request<SetterTemplate>('/api/resources/setter-templates', {
      method: 'POST',
      body: JSON.stringify(template),
    }),

  // AI 模型配置
  listAIs: () => request<AIConfig[]>('/api/resources/ai'),
  getAI: (id: ID) => request<AIConfig>(`/api/resources/ai/${id}`),
  saveAI: (ai: AIConfig) =>
    request<AIConfig>('/api/resources/ai', {
      method: 'POST',
      body: JSON.stringify(ai),
    }),
  deleteAI: (id: ID) => request<void>(`/api/resources/ai/${id}`, { method: 'DELETE' }),

  // 渠道配置
  listChannels: () => request<ChannelConfig[]>('/api/resources/channels'),
  getChannel: (id: ID) => request<ChannelConfig>(`/api/resources/channels/${id}`),
  saveChannel: (channel: ChannelConfig) =>
    request<ChannelConfig>('/api/resources/channels', {
      method: 'POST',
      body: JSON.stringify(channel),
    }),
  deleteChannel: (id: ID) =>
    request<void>(`/api/resources/channels/${id}`, { method: 'DELETE' }),

  // 凭据管理
  listCredentials: () => request<Credential[]>('/api/resources/credentials'),
  saveCredential: (credential: Credential) =>
    request<Credential>('/api/resources/credentials', {
      method: 'POST',
      body: JSON.stringify(credential),
    }),

  // Workflow 定义
  listWorkflows: () => request<WorkflowDefinition[]>('/api/resources/workflows'),
  getWorkflow: (id: ID) => request<WorkflowDefinition>(`/api/resources/workflows/${id}`),
  saveWorkflow: (workflow: WorkflowDefinition) =>
    request<WorkflowDefinition>('/api/resources/workflows', {
      method: 'POST',
      body: JSON.stringify(workflow),
    }),
  deleteWorkflow: (id: ID) =>
    request<void>(`/api/resources/workflows/${id}`, { method: 'DELETE' }),
}
