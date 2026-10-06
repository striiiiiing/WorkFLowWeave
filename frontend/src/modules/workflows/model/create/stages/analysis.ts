import type { ContinuePolicy } from '../policies'
import type { AgentTaskConfig } from './agentTask'

export interface AnalysisTask extends AgentTaskConfig {
  id: string
  ai: string
  system_prompt: string | null
  input_prompt: string | null
  user_prompt: string
  model: string
}

export interface AnalysisConfig {
  analyses: AnalysisTask[]
  analysis_concurrency: number
  analysis_failure: ContinuePolicy
}

export function createAnalysisDefaults(): AnalysisConfig {
  return { analyses: [], analysis_concurrency: 4, analysis_failure: 'continue' }
}

export function createAnalysisTask(id: string): AnalysisTask {
  return {
    id,
    ai: '',
    model: '',
    system_prompt: null,
    input_prompt: null,
    user_prompt: '',
    agent_mode: false,
    agent_tools: null,
  }
}
