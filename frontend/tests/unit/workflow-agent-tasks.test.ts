import { effectScope, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import ElementPlus, { ElCheckbox, ElSelect } from 'element-plus'
import { describe, expect, it } from 'vitest'
import {
  createWorkflow,
  useWorkflowEditor,
  createFanIn,
  validateWorkflow,
} from '@/modules/workflows/public'
import FanOutTaskCard from '@/modules/workflows/ui/FanOutTaskCard.vue'
import FanInCard from '@/modules/workflows/ui/FanInCard.vue'
import AgentTaskOptions from '@/modules/workflows/ui/AgentTaskOptions.vue'
import { changeAgentMode } from '@/modules/workflows/model/create/stages/agentTask'
import { parsePhase } from '@/modules/workflows/model/history/report'
import { sessionKind } from '@/modules/agents/model/session/sessionKind'
import type { AgentSession } from '@/modules/agents/public'

describe('Workflow Agent tasks', () => {
  it('enables LLM summary optimization by default and exposes it only in advanced LLM mode', async () => {
    const scope = effectScope()
    const editor = scope.run(() => useWorkflowEditor({ identity: 'workflow', data: undefined }))!
    editor.replace(createWorkflow())
    editor.addTask()
    editor.updateTask(0, { ai: 'provider', model: 'model' })
    editor.toggleFanIn(true)
    expect(editor.draft.value!.fan_in!.single_task_optimization).toBe(true)
    const wrapper = mount(FanInCard, {
      props: { editor, configs: [], advanced: false },
      global: { plugins: [ElementPlus] },
    })
    expect(wrapper.find('[aria-label="采用单任务优化"]').exists()).toBe(false)
    await wrapper.setProps({ advanced: true })
    await wrapper.get('[aria-label="采用单任务优化"] input').setValue(false)
    expect(editor.draft.value!.fan_in!.single_task_optimization).toBe(false)
    editor.updateFanIn({ agent_mode: true, single_task_optimization: true })
    await nextTick()
    expect(wrapper.find('[aria-label="采用单任务优化"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('采用单任务优化')
    editor.updateFanIn({ agent_mode: false })
    await nextTick()
    expect(wrapper.get('[aria-label="采用单任务优化"] input').element).toHaveProperty(
      'checked',
      true,
    )
    wrapper.unmount()
    scope.stop()
  })

  it('requires a model when an aggregation task uses Agent', () => {
    const workflow = createWorkflow()
    workflow.fan_in = { ...createFanIn(), agent_mode: true }
    expect(validateWorkflow(workflow)).toContain('Agent 汇总需要选择模型，或复用一个分析任务的模型')
    workflow.fan_in.ai = 'provider'
    workflow.fan_in.model = 'model'
    expect(validateWorkflow(workflow)).not.toContain(
      'Agent 汇总需要选择模型，或复用一个分析任务的模型',
    )
  })

  it('keeps task tools and prompts independent and hides only advanced controls', async () => {
    const scope = effectScope()
    const editor = scope.run(() => useWorkflowEditor({ identity: 'workflow', data: undefined }))!
    editor.replace(createWorkflow())
    editor.addTask()
    editor.addTask()
    editor.toggleFanIn(true)
    const wrapper = mount(FanOutTaskCard, {
      props: { editor, configs: [], advanced: true, tools: [{ name: 'read', enabled: true }] },
      global: { plugins: [ElementPlus] },
    })
    const first = wrapper.findAllComponents(AgentTaskOptions)[0]
    await first.findComponent(ElCheckbox).vm.$emit('update:modelValue', true)
    await nextTick()
    expect(editor.draft.value!.analyses[0].user_prompt).toBe('')
    expect(editor.draft.value!.analyses[1]).toMatchObject({
      agent_mode: false,
      agent_tools: null,
      user_prompt: '',
    })
    await first.findAllComponents(ElCheckbox)[1].vm.$emit('update:modelValue', false)
    await nextTick()
    expect(editor.draft.value!.analyses[0].agent_tools).toEqual([])
    await first.findComponent(ElSelect).vm.$emit('update:modelValue', ['read'])
    await nextTick()
    expect(editor.draft.value!.analyses[0].agent_tools).toEqual(['read'])
    expect(editor.draft.value!.analyses[1].agent_tools).toBeNull()
    expect(editor.draft.value!.fan_in!.agent_tools).toBeNull()
    await wrapper.setProps({ advanced: false })
    expect(first.findComponent(ElSelect).exists()).toBe(false)
    expect(editor.draft.value!.analyses[0].agent_tools).toEqual(['read'])
    wrapper.unmount()
    scope.stop()
  })

  it('does not replace an edited prompt when toggling Agent execution', () => {
    expect(changeAgentMode({ user_prompt: 'custom' }, true).user_prompt).toBe('custom')
    expect(changeAgentMode({ user_prompt: 'custom' }, false).user_prompt).toBe('custom')
    expect(changeAgentMode({ user_prompt: '原有分析指令' }, false).user_prompt).toBe('原有分析指令')
    expect(changeAgentMode({ user_prompt: '' }, true).user_prompt).toBe('')
  })

  it('opens analysis and summary Agent sessions while preserving plain LLM results', () => {
    const analyses = parsePhase('analyze', {
      analyses: [
        { task_id: 'agent', text: 'result', status: 'success', agent_session_id: 'session-a' },
        { task_id: 'llm', text: 'plain', status: 'success' },
      ],
    })
    expect(analyses.items.map((item) => item.agentSessionId)).toEqual(['session-a', undefined])
    const aggregate = parsePhase('aggregate', {
      outputs: { final: 'summary', agent: 'result' },
      aggregate: { agent_session_id: 'session-b' },
    })
    expect(aggregate.items.map((item) => item.agentSessionId)).toEqual(['session-b', undefined])
    expect(
      parsePhase('aggregate', { outputs: { final: 'old result' } }).items[0].agentSessionId,
    ).toBe(undefined)
  })

  it('retains the Agent process entry when aggregation fails without an output', () => {
    const report = parsePhase('aggregate', {
      outputs: {},
      aggregate: {
        status: 'failed',
        text: '',
        error: { message: 'tool failed' },
        agent_session_id: 'failed-session',
      },
    })
    expect(report.items).toEqual([
      {
        id: 'final',
        text: '',
        status: 'failed',
        error: 'tool failed',
        agentSessionId: 'failed-session',
      },
    ])
  })

  it('classifies legacy and task sessions for the shared session list', () => {
    expect(sessionKind({ workflow_session_id: null } as AgentSession)).toBe('standalone')
    expect(sessionKind({ workflow_session_id: 'run' } as AgentSession)).toBe('workflow_continue')
    expect(
      sessionKind({ workflow_session_id: 'run', workflow_task_id: 'task' } as AgentSession),
    ).toBe('workflow_subtask')
  })
})
