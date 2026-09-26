import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, expect, it, vi } from 'vitest'
import { type AgentEvent, type AgentFile } from '@/modules/agents/public'
import type { AgentSession, AgentSettings } from '@/modules/agents/public'
import { agentsApi } from '@/app/services'
import { ApiError } from '@/shared/api/errors'
import AgentFileDrawer from '@/modules/agents/ui/AgentFileDrawer.vue'
import AgentTranscript from '@/modules/agents/ui/AgentTranscript.vue'
import { useAgentFiles } from '@/modules/agents/composables/useAgentFiles'
import { transcriptRows } from '@/modules/agents/public'
import AgentSidebar from '@/modules/agents/ui/AgentSidebar.vue'
import AgentGlobalSettingsModal from '@/modules/agents/ui/AgentGlobalSettingsModal.vue'
import { useAgentSettings } from '@/modules/agents/composables/useAgentSettings'
import { effectScope } from 'vue'
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
})
const global = { plugins: [ElementPlus] }
const file = (content: string, hash = 'v1'): AgentFile => ({
  path: 'Memory/note.md',
  kind: 'file',
  content,
  hash,
  readonly: false,
  offset: 0,
  next_offset: null,
  total_lines: 1,
})
const event = (
  id: number,
  type: string,
  data: Record<string, unknown>,
  session = 's',
): AgentEvent => ({ id, type, data, session_id: session, turn_id: 't', at: '2026-09-23' })
const button = (wrapper: ReturnType<typeof mount>, text: string) =>
  wrapper.findAll('button').find((item) => item.text() === text)!
it('preserves the draft on conflict and explicitly adopts a refreshed version before saving', async () => {
  vi.spyOn(agentsApi, 'readFile')
    .mockResolvedValueOnce(file('original'))
    .mockResolvedValueOnce(file('external', 'v2'))
  const write = vi
    .spyOn(agentsApi, 'writeFile')
    .mockRejectedValueOnce(
      new ApiError(409, { code: 'file_conflict', message: '文件版本冲突', details: {} }),
    )
    .mockResolvedValueOnce({ hash: 'v3' })
  const files = useAgentFiles(agentsApi)
  files.reset('s', 'Memory/note.md')
  await files.read()
  const wrapper = mount(AgentFileDrawer, {
    props: { files },
    global,
  })
  wrappers.push(wrapper)
  await flushPromises()
  await wrapper.get('textarea').setValue('my draft')
  await button(wrapper, '保存').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('文件版本冲突')
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('my draft')
  await button(wrapper, '读取最新版本（保留草稿）').trigger('click')
  await flushPromises()
  expect(wrapper.get('pre').text()).toBe('external')
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('my draft')
  await button(wrapper, '使用最新版本继续合并').trigger('click')
  await wrapper.get('textarea').setValue('merged draft')
  await button(wrapper, '保存').trigger('click')
  await flushPromises()
  expect(write).toHaveBeenLastCalledWith('s', 'Memory/note.md', 'merged draft', 'v2')
})
it('never saves a partial page and reads a consistent full file before editing', async () => {
  const first = { ...file('first\n'), next_offset: 200, total_lines: 201 }
  vi.spyOn(agentsApi, 'readFile')
    .mockResolvedValueOnce(first)
    .mockResolvedValueOnce(first)
    .mockResolvedValueOnce({ ...file('last'), offset: 200, total_lines: 201 })
  const write = vi.spyOn(agentsApi, 'writeFile').mockResolvedValue({ hash: 'saved' })
  const files = useAgentFiles(agentsApi)
  files.reset('s', 'Memory/note.md')
  await files.read()
  const wrapper = mount(AgentFileDrawer, {
    props: { files },
    global,
  })
  wrappers.push(wrapper)
  await flushPromises()
  expect(button(wrapper, '保存').attributes('disabled')).toBeDefined()
  expect(wrapper.get('textarea').attributes('readonly')).toBeDefined()
  await button(wrapper, '载入全文编辑').trigger('click')
  await flushPromises()
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('first\nlast')
  await wrapper.get('input[aria-label="文件路径"]').setValue('Memory/another.md')
  await button(wrapper, '保存').trigger('click')
  await flushPromises()
  expect(write).toHaveBeenCalledWith('s', 'Memory/note.md', 'first\nlast', 'v1')
})
it('shows Runtime as read only using the backend flag', async () => {
  vi.spyOn(agentsApi, 'readFile').mockResolvedValue({ ...file('runtime'), readonly: true })
  const files = useAgentFiles(agentsApi)
  files.reset('s', 'Runtime/self.json')
  await files.read()
  const wrapper = mount(AgentFileDrawer, {
    props: { files },
    global,
  })
  wrappers.push(wrapper)
  await flushPromises()
  expect(wrapper.text()).toContain('运行时文件只读')
  expect(button(wrapper, '保存').attributes('disabled')).toBeDefined()
  expect(wrapper.get('textarea').attributes('readonly')).toBeDefined()
})
it('merges stream deltas and tool statuses, keeps old messages at compaction, and allows only current user edits', async () => {
  const events = [
    event(1, 'message.user', { text: 'parent text', message_id: 'p' }, 'parent'),
    event(1, 'message.user', { text: 'current', message_id: 'u' }),
    event(2, 'message.delta', { content: '**safe**', message_id: 'a' }),
    event(3, 'message.delta', {
      content: '<img src=x onerror=alert(1)> [bad](javascript:alert(1))',
      message_id: 'a',
    }),
    event(4, 'tool.queued', {
      tool_call_id: 'call',
      name: 'plugin',
      execution: 'read',
      arguments: { target: 'sources:mock' },
    }),
    event(5, 'tool.started', {
      tool_call_id: 'call',
      name: 'plugin',
      execution: 'read',
      arguments: { target: 'sources:mock' },
    }),
    event(6, 'tool.completed', {
      tool_call_id: 'call',
      name: 'plugin',
      execution: 'read',
      arguments: { target: 'sources:mock' },
      result: { status: 'success', artifact_path: 'Artifacts/result.json', duration_ms: 2 },
    }),
    event(7, 'message.completed', { incremental: true, text: 'should not duplicate' }),
    event(8, 'context.compacted', {
      summary: 'summary',
      artifact_path: 'History/s/summaries/1.md',
      source_event_range: { start: 1, end: 7 },
    }),
  ]
  const original = JSON.stringify(events)
  const wrapper = mount(AgentTranscript, {
    props: { events, running: false, sessionId: 's' },
    global,
  })
  wrappers.push(wrapper)
  expect(wrapper.findAll('.role-assistant')).toHaveLength(1)
  expect(wrapper.findAll('.tool-call')).toHaveLength(1)
  expect(wrapper.text()).toContain('parent text')
  expect(wrapper.text()).toContain('sources:mock')
  expect(wrapper.text()).not.toContain('should not duplicate')
  expect(wrapper.find('img').exists()).toBe(false)
  expect(wrapper.find('a[href^="javascript:"]').exists()).toBe(false)
  expect(wrapper.findAll('button').filter((item) => item.text() === '编辑并创建分支')).toHaveLength(
    1,
  )
  await button(wrapper, '编辑并创建分支').trigger('click')
  expect(wrapper.emitted('edit')?.[0][0]).toEqual(events[1])
  await button(wrapper, '读取完整输出').trigger('click')
  expect(wrapper.emitted('file')?.[0]).toEqual(['Runtime/Artifacts/result.json'])
  await wrapper.setProps({ running: true })
  expect(button(wrapper, '编辑并创建分支').attributes('disabled')).toBeDefined()
  expect(JSON.stringify(events)).toBe(original)
})
it('does not group later dependent reads into the previous parallel group', () => {
  const rows = transcriptRows([
    event(1, 'tool.queued', { tool_call_id: 'a', execution: 'read' }),
    event(2, 'tool.queued', { tool_call_id: 'b', execution: 'read' }),
    event(3, 'tool.completed', { tool_call_id: 'a', execution: 'read' }),
    event(4, 'tool.completed', { tool_call_id: 'b', execution: 'read' }),
    event(5, 'tool.queued', { tool_call_id: 'c', execution: 'read' }),
  ])
  expect(rows[0].group).toBe(rows[1].group)
  expect(rows[2].group).not.toBe(rows[0].group)
})
it('keeps the parent branch visible and selects the child without mutating session metadata', async () => {
  const sessions = [
    { session_id: 'p', branch_id: 'main', status: 'completed' },
    {
      session_id: 'c',
      branch_id: 'branch',
      status: 'created',
      parent_session_id: 'p',
      parent_branch_id: 'main',
    },
  ] as AgentSession[]
  const wrapper = mount(AgentSidebar, { props: { sessions, selectedId: 'c' }, global })
  wrappers.push(wrapper)
  expect(wrapper.findAll('.agent-session')).toHaveLength(2)
  expect(wrapper.get('.agent-session.active').text()).toContain('branch')
  expect(wrapper.text()).toContain('main')
  await wrapper.findAll('.agent-session')[0].trigger('click')
  expect(wrapper.emitted('select')?.[0][0]).toEqual(sessions[0])
  expect(sessions[1].parent_session_id).toBe('p')
})
it('edits persistent settings, exposes disabled tools, and uses the existing plugin toggle endpoint', async () => {
  const settings = {
    config: {
      context_window: 200000,
      output_tokens: 4096,
      trigger_tokens: 180000,
      keep_tokens: 40000,
      summary_ai: null,
      summary_context_window: null,
      summary_max_tokens: 4096,
      summary_prompt: 'summary',
      timezone: 'Asia/Shanghai',
      read_concurrency: 4,
      idle_timeout: 300,
      sandbox: { enabled: false, network: false },
    },
    models: [],
    tools: [
      {
        name: 'shell',
        plugin: 'agent_shell',
        description: 'disabled',
        enabled: false,
        generation: 2,
        execution: null,
        input_schema: null,
        definition_tokens: 0,
      },
    ],
    sandbox: { enabled: false, network: false, available: false, status: 'disabled' },
    scheduler: { reading: 0, writing: 0, queued: 0, read_concurrency: 4 },
    readonly_paths: ['Runtime/self.json'],
  } as AgentSettings
  vi.spyOn(agentsApi, 'config').mockResolvedValue(settings)
  const save = vi.spyOn(agentsApi, 'updateConfig').mockResolvedValue(settings.config)
  const toggle = vi.spyOn(agentsApi, 'updateTool').mockResolvedValue({})
  const scope = effectScope()
  const controller = scope.run(() => useAgentSettings(agentsApi))!
  const wrapper = mount(AgentGlobalSettingsModal, {
    props: { modelValue: true, controller },
    attachTo: document.body,
    global,
  })
  wrappers.push(wrapper)
  await flushPromises()
  const tab = (name: string) =>
    [...document.querySelectorAll('[role="tab"]')].find((item) =>
      item.textContent?.includes(name),
    ) as HTMLElement
  tab('工具插件与调度').click()
  await flushPromises()
  expect(document.body.textContent).toContain('disabled')
  await wrapper.find('.tool-switch').findComponent({ name: 'ElSwitch' }).vm.$emit('change', true)
  await flushPromises()
  expect(toggle).toHaveBeenCalledWith('agent_shell', true)
  tab('基础设置').click()
  await flushPromises()
  const timezone = document.querySelector('input[placeholder="Asia/Shanghai"]') as HTMLInputElement
  timezone.value = 'UTC'
  timezone.dispatchEvent(new Event('input', { bubbles: true }))
  ;[...document.querySelectorAll('button')]
    .find((item) => item.textContent?.trim() === '保存全局设置')!
    .click()
  await flushPromises()
  expect(save).toHaveBeenCalledWith(expect.objectContaining({ timezone: 'UTC', idle_timeout: 300 }))
  scope.stop()
})
