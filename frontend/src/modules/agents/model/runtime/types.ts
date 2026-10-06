export interface ContextBudget {
  messages: number
  system: number
  tools: number
  output: number
  total: number
  window: number
  trigger?: number
  remaining: number
  estimated: boolean
  token_counter: string
}

export interface AgentEvent {
  id: number
  session_id: string
  turn_id: string | null
  type: string
  at: string
  data: Record<string, unknown>
}

export interface AgentTool {
  name: string
  description: string
  execution: 'read' | 'exclusive' | null
  input_schema: Record<string, unknown> | null
  enabled: boolean
  registered?: boolean
  plugin: string
  generation: number | null
  definition_tokens: number
}

export interface AgentConfig {
  context_window: number | null
  output_tokens: number
  trigger_tokens: number
  keep_tokens: number
  summary_ai: string | null
  summary_context_window: number | null
  summary_max_tokens: number
  summary_prompt: string
  timezone: string
  sandbox: { enabled: boolean; network: boolean }
  idle_timeout: number
  read_concurrency: number
  [key: string]: unknown
}

export interface AgentSettings {
  config: AgentConfig
  models: import('../session/models').AgentModel[]
  tools: AgentTool[]
  scheduler: Record<string, number>
  sandbox: { enabled: boolean; network: boolean; available: boolean; status: string }
  readonly_paths: string[]
}

export interface TurnAccepted {
  turn_id: string
  session_id: string
  deduplicated: boolean
  status?: string
}
