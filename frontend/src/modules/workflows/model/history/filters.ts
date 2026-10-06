export const fields = [
  { value: 'workflow_name', label: '工作流名称', placeholder: '输入名称关键词（包含匹配）' },
  { value: 'workflow_id', label: '工作流 ID', placeholder: '输入完整工作流 ID' },
  { value: 'session_id', label: 'Session ID', placeholder: '输入完整 Session ID' },
  { value: 'status', label: '运行状态', placeholder: '选择运行状态' },
] as const
export type FilterField = (typeof fields)[number]['value']
