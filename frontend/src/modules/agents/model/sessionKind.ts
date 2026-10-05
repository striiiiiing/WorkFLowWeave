import type { AgentSession } from './types'

export const sessionKindLabels = {
  standalone: '独立会话',
  workflow_continue: 'Workflow 继续会话',
  workflow_subtask: 'Workflow 子任务',
}

export function sessionKind(session: AgentSession): keyof typeof sessionKindLabels {
  return (
    session.session_kind ??
    (session.workflow_session_id
      ? session.workflow_task_id
        ? 'workflow_subtask'
        : 'workflow_continue'
      : 'standalone')
  )
}
