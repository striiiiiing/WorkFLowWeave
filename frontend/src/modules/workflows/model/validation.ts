import type { WorkflowDefinition } from './types'

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
  if (!workflow.sources.length) errors.push('至少选择一个采集源')
  if (!workflow.analyses.length) errors.push('至少添加一个分析任务')
  workflow.analyses.forEach((task, index) => {
    const error = validateAnalysisId(workflow, index, task.id)
    if (error) errors.push(error)
  })
  return errors
}
