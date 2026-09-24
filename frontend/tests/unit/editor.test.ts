import { defineComponent, ref } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus, { ElInput, ElRadioGroup, ElSelect } from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ResourceEditor from '@/components/resources/ResourceEditor.vue'
import SourceStepCard from '@/components/workflow/SourceStepCard.vue'
import FanOutTaskCard from '@/components/workflow/FanOutTaskCard.vue'
import NotificationCard from '@/components/workflow/NotificationCard.vue'
import { createResource } from '@/domain/resources'
import { createWorkflow } from '@/domain/workflow'
import { resourcesApi } from '@/api/resources'
import { systemApi } from '@/api/system'

vi.mock('@/api/resources', () => ({
  resourcesApi: { create: vi.fn(), replace: vi.fn(), protectCredential: vi.fn() },
}))
vi.mock('@/api/system', () => ({ systemApi: { plugins: vi.fn().mockResolvedValue([]) } }))
const global = { plugins: [ElementPlus] }
afterEach(() => vi.clearAllMocks())

describe('editor task regressions', () => {
  it('defaults new channels to the supported OpenAI compatible API format', () => {
    const ai = createResource('ai')
    expect(ai.provider).toBe('openai_compatible_api')
    expect(ai.base_url).toBeNull()
  })

  it('generates distinct UUID resource IDs and includes counts for new workflows', () => {
    const values = ['sources', 'ai', 'channels'].map((kind) => createResource(kind as 'sources'))
    values.push(createResource('sources'))
    expect(new Set(values.map((item) => item.id)).size).toBe(4)
    for (const item of values) expect(item.id).toMatch(/^[0-9a-f-]{36}$/)
    expect(createWorkflow().include_counts).toBe(true)
  })

  it('shows the resource ID normally and saves a generated ID with schema-selected collector', async () => {
    vi.mocked(systemApi.plugins).mockResolvedValueOnce([
      {
        kind: 'collector',
        name: 'mock',
        description: 'test collector',
        plugin: 'builtin',
        capabilities: [],
        options_schema: { type: 'object', properties: {} },
        setters_schema: null,
        fields: [],
        count_unit: 'records',
      },
    ])
    const wrapper = mount(ResourceEditor, { props: { kind: 'sources' }, global })
    await flushPromises()
    expect(wrapper.text()).toContain('资源编号')
    expect(wrapper.get('input[placeholder="可自行填写；留空则自动生成"]').isVisible()).toBe(true)
    wrapper.findComponent(ElSelect).vm.$emit('update:modelValue', 'mock')
    await flushPromises()
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(resourcesApi.create).toHaveBeenCalledWith(
      'sources',
      expect.objectContaining({ collector: 'mock', id: expect.stringMatching(/^[0-9a-f-]{36}$/) }),
    )
    wrapper.unmount()
  })

  it('protects an entered key before resource save and retains ciphertext after save failure', async () => {
    const encrypted = {
      kind: 'encrypted' as const,
      format_version: 1,
      key_id: 'key-id',
      ciphertext: 'ciphertext',
    }
    vi.mocked(resourcesApi.protectCredential).mockResolvedValueOnce(encrypted)
    vi.mocked(resourcesApi.create)
      .mockRejectedValueOnce(new Error('save failed'))
      .mockImplementationOnce(async (_kind, value) => JSON.parse(JSON.stringify(value)))
    const wrapper = mount(ResourceEditor, { props: { kind: 'ai' }, global })
    await flushPromises()
    wrapper.findComponent(ElRadioGroup).vm.$emit('update:modelValue', 'openai_compatible_api')
    wrapper
      .findAllComponents(ElInput)
      .find((item) => item.props('placeholder') === 'https://api.openai.com/v1')!
      .vm.$emit('update:modelValue', 'http://127.0.0.1:1/v1')
    await wrapper.find('input[type="password"]').setValue('test-only-key')
    expect(wrapper.find('input[type="password"]').element.getAttribute('type')).toBe('password')
    await wrapper.find('.el-input__password').trigger('click')
    expect(wrapper.find('input[autocomplete="new-password"]').attributes('type')).toBe('text')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(resourcesApi.protectCredential).toHaveBeenCalledWith('test-only-key')
    expect(resourcesApi.create).toHaveBeenLastCalledWith(
      'ai',
      expect.objectContaining({ api_key: encrypted }),
    )
    expect(wrapper.text()).toContain('save failed')
    expect(wrapper.find('input[autocomplete="new-password"]').exists()).toBe(false)
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(resourcesApi.protectCredential).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('saved')).toHaveLength(1)
    wrapper.unmount()
  })

  it('reports credential protection failures without saving an unprotected resource', async () => {
    vi.mocked(resourcesApi.protectCredential).mockRejectedValueOnce(new Error('master key missing'))
    const initial = {
      ...createResource('ai'),
      provider: 'http',
      base_url: 'http://127.0.0.1:1/v1',
    }
    const wrapper = mount(ResourceEditor, { props: { kind: 'ai', initial }, global })
    await flushPromises()
    wrapper.findComponent(ElSelect).vm.$emit('update:modelValue', 'input')
    await flushPromises()
    await wrapper.find('input[type="password"]').setValue('test-key')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('master key missing')
    expect(resourcesApi.replace).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('reorders shared input sources without losing their overrides and removes only deselected overrides', async () => {
    const workflow = ref({
      ...createWorkflow(),
      sources: ['first', 'second'],
      source_overrides: { first: { options: { limit: 3 }, setters: {}, template: null } },
    })
    const sources = ['first', 'second'].map((id) => ({
      ...createResource('sources'),
      id,
      collector: 'mock',
    }))
    const wrapper = mount(
      defineComponent({
        components: { SourceStepCard },
        setup: () => ({ workflow, sources }),
        template:
          '<el-form :model="workflow"><SourceStepCard v-model="workflow" :sources="sources" /></el-form>',
      }),
      { global },
    )
    await flushPromises()
    expect(wrapper.text()).not.toContain('采集并发数')
    await wrapper.find('[aria-label="上移 second"]').trigger('click')
    expect(workflow.value.sources).toEqual(['second', 'first'])
    expect(workflow.value.source_overrides.first.options).toEqual({ limit: 3 })
    await wrapper
      .get('article[aria-label="数据源 first"]')
      .findAll('button')
      .find((button) => button.text() === '移除')!
      .trigger('click')
    await flushPromises()
    expect(workflow.value.source_overrides).toEqual({})
    wrapper.unmount()
  })

  it('advanced visibility does not reset existing workflow policies', async () => {
    const workflow = ref({ ...createWorkflow(), analysis_concurrency: 7, send_partial: false })
    const advanced = ref(false)
    const wrapper = mount(
      defineComponent({
        components: { FanOutTaskCard, NotificationCard },
        setup: () => ({ workflow, advanced }),
        template:
          '<el-form :model="workflow"><FanOutTaskCard v-model="workflow" :configs="[]" :advanced="advanced" /><NotificationCard v-model="workflow" :channels="[]" :advanced="advanced" /></el-form>',
      }),
      { global },
    )
    expect(wrapper.text()).not.toContain('分析失败时')
    expect(wrapper.text()).not.toContain('允许发送部分成功的结果')
    advanced.value = true
    await flushPromises()
    expect(wrapper.text()).toContain('分析失败时')
    advanced.value = false
    await flushPromises()
    expect(workflow.value.analysis_concurrency).toBe(7)
    expect(workflow.value.send_partial).toBe(false)
    wrapper.unmount()
  })
})

// UI fields must preserve the API distinction between resource and call options.
describe('capability form scope', () => {
  it('defers required call options and excludes instance-only fields in a workflow', async () => {
    const { optionSchema, partialSchema } = await import('@/shared/schema/capabilities')
    const schema = {
      type: 'object',
      required: ['account', 'limit'],
      properties: {
        account: { type: 'string' },
        limit: { type: 'integer', 'x-logagent-workflow': true },
      },
    }
    expect(optionSchema(schema, 'resource')?.required).toEqual(['account'])
    expect(optionSchema(schema, 'workflow')).toEqual({
      ...schema,
      required: [],
      properties: { limit: schema.properties.limit },
      additionalProperties: false,
    })
    expect(partialSchema(schema)?.required).toEqual([])
    expect(schema.required).toEqual(['account', 'limit'])
  })
})
