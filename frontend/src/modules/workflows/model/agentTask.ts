import type { AgentTaskConfig } from './types'

export function changeAgentMode(task: AgentTaskConfig & { user_prompt: string }, enabled: boolean) {
  return { agent_mode: enabled, user_prompt: task.user_prompt }
}
