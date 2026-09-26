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
    global: { plugins: [ElementPlus] },
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

it('renders plugin sections and delivery uncertainty without inventing success', async () => {
  vi.mocked(runsApi.phase).mockResolvedValue({
    ...phase,
    stage: 'collect',
    content: {
      collection: [
        {
          source_id: 'logs',
          status: 'success',
          text: 'AI input',
          count: 2,
          report: {
            sections: [
              {
                kind: 'metrics',
                title: '告警',
                items: [{ label: '错误数量', value: 2, unit: '条' }],
              },
              { kind: 'table', title: '详情', columns: ['内容'], rows: [['网络中断']] },
            ],
          },
        },
      ],
    },
  })
  const wrapper = mount(ReportHarness, {
    props: { id: 'run', version: 3, stage: 'collect', active: false, advanced: false },
    global: { plugins: [ElementPlus] },
  })
  wrappers.push(wrapper)
  await vi.dynamicImportSettled()
  await flushPromises()
  expect(wrapper.text()).toContain('错误数量')
  expect(wrapper.get('table').text()).toContain('网络中断')
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
