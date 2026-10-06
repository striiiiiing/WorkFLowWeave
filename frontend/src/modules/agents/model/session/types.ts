export interface AgentSession {
  session_id: string
  branch_id: string
  title?: string
  model: string | null
  workflow_session_id: string | null
  session_kind?: 'standalone' | 'workflow_continue' | 'workflow_subtask'
  workflow_task_id?: string | null
  created_at: string
  updated_at: string
  status: string
  turn_id: string | null
  parent_session_id?: string | null
  parent_turn_id?: string | null
  parent_branch_id?: string | null
  parent_event_id?: number | null
  context_budget: import('../runtime/types').ContextBudget | null
  continuable: boolean
  history_path: string
  last_checkpoint_at: string | null
  continuation_error?: { code: string; message: string } | null
  active_resources?: { model: string | null; tools_generation: number | null } | null
}
