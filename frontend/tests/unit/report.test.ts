import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, expect, it, vi } from 'vitest'
import { runsApi } from '@/app/services'
import { computed, defineComponent } from 'vue'
import {
  parsePhase,
  unavailableText,
  PhaseReport,
  usePhaseReport,
  type WorkflowStage,
} from '@/modules/runs/public'
const ReportHarness = defineComponent({
  components: { PhaseReport },
  props: {
    id: { type: String, required: true },
    version: { type: Number, required: true },
    stage: { type: String, required: true },
    active: Boolean,
    advanced: Boolean,
  },
  setup(props) {
    return {
      report: usePhaseReport(
        computed(() => ({
          id: props.id,
          version: props.version,
          stage: props.stage as WorkflowStage,
        })),
        runsApi,
      ),
    }
  },
  template: '<PhaseReport :report="report" :active="active" :advanced="advanced" />',
})
const RouterLinkStub = defineComponent({
  props: { to: { type: [String, Object], required: true } },
  template: '<a><slot /></a>',
})
import ReportText from '@/shared/ui/ReportText.vue'
import type { PhaseContent } from '@/modules/runs/public'

vi.mock('@/app/services', () => ({ runsApi: { phase: vi.fn() } }))
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => {
  wrappers.forEach((wrapper) => wrapper.unmount())
  wrappers.length = 0
  vi.clearAllMocks()
})
const phase: PhaseContent = {
  session_id: 'run',
  version: 3,
  stage: 'aggregate',
  availability: 'available',
  size_bytes: null,
  error: null,
  content: { outputs: { final: '# 今日报告\n\n已完成分析。' } },
}

it('renders readable output by default, exposes JSON only in advanced mode, and clears stale versions', async () => {
  vi.mocked(runsApi.phase).mockResolvedValue(phase)
  const wrapper = mount(ReportHarness, {
    props: { id: 'run', version: 3, stage: 'aggregate', active: false, advanced: false },
    global: { plugins: [ElementPlus], stubs: { RouterLink: RouterLinkStub } },
  })
  wrappers.push(wrapper)
  await vi.dynamicImportSettled()
  await flushPromises()
  expect(wrapper.get('h1').text()).toBe('今日报告')
  expect(wrapper.find('pre').exists()).toBe(false)
  await wrapper.setProps({ advanced: true })
  expect(wrapper.get('pre').text()).toContain('outputs')
  let finish!: (value: PhaseContent) => void
  vi.mocked(runsApi.phase).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve
      }),
  )
  await wrapper.setProps({ version: 4 })
  expect(wrapper.text()).not.toContain('今日报告')
  expect(runsApi.phase).toHaveBeenLastCalledWith('run', 'aggregate', 4, expect.any(AbortSignal))
  finish({ ...phase, version: 4, availability: 'expired', content: null })
  await flushPromises()
  expect(wrapper.text()).toContain('已过期')
  expect(wrapper.find('pre').exists()).toBe(false)
})

it('links an Agent analysis report to its session', async () => {
  vi.mocked(runsApi.phase).mockResolvedValue({
    ...phase,
    stage: 'analyze',
    content: {
      analyses: [
        {
          task_id: 'agent-task',
          text: '分析结果',
          status: 'success',
          agent_session_id: 'agent-session-1',
        },
      ],
    },
  })
  const wrapper = mount(ReportHarness, {
    props: { id: 'run', version: 3, stage: 'analyze', active: false, advanced: false },
    global: { plugins: [ElementPlus], stubs: { RouterLink: RouterLinkStub } },
  })
  wrappers.push(wrapper)
  await vi.dynamicImportSettled()
  await flushPromises()
  const link = wrapper.findComponent(RouterLinkStub)
  expect(link.props('to')).toEqual({
    name: 'agent-session',
    params: { sessionId: 'agent-session-1' },
  })
  expect(link.text()).toContain('查看 Agent 过程 / 继续会话')
})

it('renders CLI raw output and processing state without inventing a count', async () => {
  vi.mocked(runsApi.phase).mockResolvedValue({
    ...phase,
    stage: 'collect',
    content: {
      collection: [
        {
          source_id: 'logs',
          status: 'success',
          raw: { stdout: '原始输出', stderr: '诊断信息', exit_code: 0 },
        },
      ],
      input_views: [
        { source_id: 'logs', status: 'success', text: '分析输入', truncated: true, omitted: false },
      ],
    },
  })
  const wrapper = mount(ReportHarness, {
    props: { id: 'run', version: 3, stage: 'collect', active: false, advanced: false },
    global: { plugins: [ElementPlus], stubs: { RouterLink: RouterLinkStub } },
  })
  wrappers.push(wrapper)
  await vi.dynamicImportSettled()
  await flushPromises()
  expect(wrapper.text()).toContain('原始输出')
  expect(wrapper.text()).toContain('诊断信息')
  expect(wrapper.text()).toContain('退出码 0')
  expect(wrapper.text()).toContain('内容已截取')
  expect(wrapper.text()).not.toContain('采集数量')
  expect(wrapper.get('details').text()).toContain('分析输入')
  const parsed = parsePhase('notify', {
    deliveries: [
      {
        channel_id: 'mail',
        output_id: 'final',
        status: 'failed',
        error: { code: 'delivery_uncertain', message: '没有可靠回执' },
      },
    ],
  })
  expect(parsed.items[0].status).toBe('uncertain')
  expect(() => parsePhase('aggregate', { other: 'unsupported' })).toThrow('结果结构')
  expect(unavailableText('pending', false)).toContain('没有此阶段')
})

it('renders MCP content, structured data, and a failed collection error', () => {
  const parsed = parsePhase('collect', {
    collection: [
      {
        source_id: 'tool',
        status: 'success',
        raw: {
          content: [{ type: 'text', text: '工具正文' }],
          structuredContent: { result: 2 },
        },
      },
      {
        source_id: 'missing',
        status: 'failed',
        raw: null,
        error: { code: 'mcp_failed', message: '服务不可用' },
      },
    ],
    input_views: [{ source_id: 'missing', status: 'skipped', omitted: true }],
  })
  expect(parsed.items[0].text).toContain('工具正文')
  expect(parsed.items[0].text).toContain('"result": 2')
  expect(parsed.items[1]).toMatchObject({
    error: '服务不可用',
    omitted: true,
    processingStatus: 'skipped',
  })
})

it('does not execute HTML or unsafe URLs inside reports', () => {
  const wrapper = mount(ReportText, {
    props: { text: '<img src=x onerror=alert(1)>\n\n[bad](javascript:alert(1))\n\n**正常文字**' },
  })
  wrappers.push(wrapper)
  expect(wrapper.find('img').exists()).toBe(false)
  expect(wrapper.find('a').exists()).toBe(false)
  expect(wrapper.get('strong').text()).toBe('正常文字')
})

it('marks report code blocks and inline code for theme-aware styling', () => {
  const wrapper = mount(ReportText, {
    props: { text: '字段 `level`\n\n```json\n{"level":"INFO"}\n```' },
  })
  wrappers.push(wrapper)
  expect(wrapper.get('code').text()).toBe('level')
  expect(wrapper.find('pre').exists()).toBe(true)
})
