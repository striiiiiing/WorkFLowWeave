export interface AgentTaskConfig {
  agent_mode?: boolean
  agent_tools?: string[] | null
}

export function changeAgentMode(task: AgentTaskConfig & { user_prompt: string }, enabled: boolean) {
  return { agent_mode: enabled, user_prompt: task.user_prompt }
}
