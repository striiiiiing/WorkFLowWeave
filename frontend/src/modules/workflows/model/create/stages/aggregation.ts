import type { AgentTaskConfig } from './agentTask'
import type { AnalysisTask } from './analysis'

export interface FanInConfig extends AgentTaskConfig {
  single_task_optimization?: boolean
  order: string[]
  separator: string
  ai: string | null
  system_prompt: string | null
  input_prompt: string | null
  user_prompt: string
  reuse_from: string | null
  model: string | null
  mark_incomplete: boolean
}

export function defaultFanInModelSource(analyses: readonly AnalysisTask[]): string | null {
  return analyses.length ? '$first' : null
}

export function createFanIn(analyses: readonly AnalysisTask[] = []): FanInConfig {
  return {
    single_task_optimization: true,
    order: [],
    separator: '\n\n',
    ai: null,
    model: null,
    system_prompt: null,
    input_prompt: null,
    user_prompt: '',
    agent_mode: false,
    agent_tools: null,
    reuse_from: defaultFanInModelSource(analyses),
    mark_incomplete: true,
  }
}
