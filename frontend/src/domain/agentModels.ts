import type { AgentModel } from '@/api/agents'

const DEFAULT_MODEL_KEY = 'logagent.agent.default-model'

/** Only a resource reference is stored; credentials remain in ResourceStore. */
export function readDefaultAgentModel(): string {
  return localStorage.getItem(DEFAULT_MODEL_KEY) ?? ''
}

export function saveDefaultAgentModel(reference: string): void {
  if (reference) localStorage.setItem(DEFAULT_MODEL_KEY, reference)
  else localStorage.removeItem(DEFAULT_MODEL_KEY)
}

export function groupAgentModels(models: AgentModel[]) {
  const sorted = [...models].sort(
    (a, b) =>
      a.ai.localeCompare(b.ai, 'zh-CN', { numeric: true }) ||
      a.model.localeCompare(b.model, 'zh-CN', { numeric: true }),
  )
  return [...new Set(sorted.map((item) => item.ai))].map((channel) => ({
    channel,
    models: sorted.filter((item) => item.ai === channel),
  }))
}
