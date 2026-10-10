import type { WorkflowDefinition } from './definition'
import { retentionFields } from './backup'

export const workflowIdPattern = /^[a-zA-Z0-9][a-zA-Z0-9_.-]*$/

export function validateWorkflowId(value: string): string {
  if (!value) return '请输入工作流 ID'
  if (!workflowIdPattern.test(value)) return '只能包含字母、数字、点、下划线和连字符'
  return ''
}

export function validateAnalysisId(
  workflow: WorkflowDefinition,
  index: number,
  value: string,
): string {
  if (!workflowIdPattern.test(value)) return '任务编号只能包含字母、数字、点、下划线和连字符'
  if (workflow.analyses.some((task, taskIndex) => taskIndex !== index && task.id === value))
    return '任务编号不能重名，请使用其他名称'
  return ''
}

export function validateWorkflow(workflow: WorkflowDefinition): string[] {
  const errors: string[] = []
  const idError = validateWorkflowId(workflow.id)
  if (idError) errors.push(idError)
  if (!workflow.analyses.length) errors.push('至少添加一个分析任务')
  if (!workflow.input_prompt.trim()) errors.push('Workflow 输入模板不能为空')
  workflow.analyses.forEach((task, index) => {
    const error = validateAnalysisId(workflow, index, task.id)
    if (error) errors.push(error)
    if (!task.user_prompt.trim()) errors.push(`任务 ${task.id} 需要填写差异提示词`)
    if (!(task.input_prompt ?? workflow.input_prompt).trim())
      errors.push(`任务 ${task.id} 的输入模板不能为空`)
  })
  if (workflow.fan_in?.agent_mode && !workflow.fan_in.reuse_from && !workflow.fan_in.ai)
    errors.push('Agent 汇总需要选择模型，或复用一个分析任务的模型')
  if (
    workflow.fan_in &&
    (workflow.fan_in.ai || workflow.fan_in.reuse_from !== null) &&
    !workflow.fan_in.user_prompt.trim()
  )
    errors.push('AI 汇总需要填写差异提示词')
  if (workflow.fan_in && !(workflow.fan_in.input_prompt ?? workflow.input_prompt).trim())
    errors.push('汇总的输入模板不能为空')
  errors.push(...validateBackupPolicy(workflow.backup))
  return errors
}

export function validateBackupPolicy(backup: WorkflowDefinition['backup']): string[] {
  const errors: string[] = []
  for (const { key, label } of retentionFields) {
    const days = backup[key]
    if (days !== null && (!Number.isSafeInteger(days) || days <= 0))
      errors.push(`${label}必须是大于 0 的整数或留空`)
  }
  return errors
}
