import { resourcesApiKey } from '@/modules/resources/api/dependencies'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AIProviderEditor from '@/modules/resources/ui/AIProviderEditor.vue'
import { resourcesApi } from '@/app/services'
import { createResource } from '@/modules/resources/public'
import type { AIConfig } from '@/modules/resources/public'

vi.mock('@/app/services', () => ({
  resourcesApi: {
    list: vi.fn(),
    create: vi.fn(),
    replace: vi.fn(),
    protectCredential: vi.fn(),
    checkAIConnection: vi.fn(),
  },
}))

const global = { plugins: [ElementPlus], provide: { [resourcesApiKey as symbol]: resourcesApi } }

function config(overrides: Partial<AIConfig> = {}): AIConfig {
  return {
    ...(createResource('ai') as AIConfig),
    id: 'provider',
    provider: 'http',
    base_url: 'https://example.test/v1',
    api_key: null,
    models: {},
    ...overrides,
  }
}

function button(wrapper: ReturnType<typeof mount>, text: string) {
  return wrapper.findAll('button').find((item) => item.text() === text)!
}

afterEach(() => vi.clearAllMocks())

describe('AI provider editor', () => {
  it('keeps health checking inside the editor and disables it for an unsaved connection', async () => {
    const wrapper = mount(AIProviderEditor, { global })
    await flushPromises()

    const health = button(wrapper, '检查健康')
    expect(health.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('保存渠道后，可在这里独立检查健康。')

    await health.trigger('click')
    await flushPromises()

    expect(resourcesApi.checkAIConnection).not.toHaveBeenCalled()
    expect(resourcesApi.create).not.toHaveBeenCalled()
    expect(resourcesApi.replace).not.toHaveBeenCalled()
    expect(resourcesApi.protectCredential).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('checks a saved connection without saving and only adds discovered models explicitly', async () => {
    vi.mocked(resourcesApi.checkAIConnection).mockResolvedValue([
      'vendor.model/pro',
      'vendor.model/flash',
    ])
    const wrapper = mount(AIProviderEditor, {
      props: {
        initial: config({ models: { existing: {} } }),
      },
      global,
    })
    await flushPromises()

    await button(wrapper, '检查健康').trigger('click')
    await flushPromises()

    expect(resourcesApi.checkAIConnection).toHaveBeenCalledWith('provider')
    expect(resourcesApi.create).not.toHaveBeenCalled()
    expect(resourcesApi.replace).not.toHaveBeenCalled()
    expect(resourcesApi.protectCredential).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('连接正常，发现 2 个模型')
    expect(wrapper.text()).not.toContain('vendor.model/pro')

    const input = wrapper.get('input[aria-label="模型名称"]')
    await input.setValue('vendor.model/pro')
    await button(wrapper, '添加模型').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('vendor.model/pro')
    expect(wrapper.text()).toContain('existing')
    wrapper.unmount()
  })

  it('rejects duplicate and unfinished model names before saving', async () => {
    const initial = config({ models: { 'vendor.model/pro': {} } })
    vi.mocked(resourcesApi.replace).mockResolvedValue(initial)
    const wrapper = mount(AIProviderEditor, { props: { initial }, global })
    await flushPromises()

    const input = wrapper.get('input[aria-label="模型名称"]')
    await input.setValue('vendor.model/pro')
    await button(wrapper, '添加模型').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('此渠道已添加该模型')

    await input.setValue('vendor.model/unfinished')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('请添加正在填写的模型，或清空模型名称')
    expect(resourcesApi.replace).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('keeps a failed health check from clearing content and still emits the complete saved result', async () => {
    const initial = config({ models: { 'vendor.model/pro': {} } })
    const saved = config({
      models: { 'vendor.model/pro': {}, 'vendor.model/flash': {} },
    })
    vi.mocked(resourcesApi.checkAIConnection).mockRejectedValue(new Error('上游 HTTP 405'))
    vi.mocked(resourcesApi.replace).mockResolvedValue(saved)
    const wrapper = mount(AIProviderEditor, { props: { initial }, global })
    await flushPromises()

    await button(wrapper, '检查健康').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('上游 HTTP 405')
    expect(wrapper.text()).toContain('vendor.model/pro')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(resourcesApi.replace).toHaveBeenCalledWith('ai', 'provider', initial)
    expect(wrapper.emitted('saved')?.[0]).toEqual([saved])
    expect(wrapper.text()).toContain('vendor.model/pro')
    wrapper.unmount()
  })

  it('supports dotted and slashed model names while preserving invalid parameter combinations', async () => {
    const initial = config({
      models: { 'vendor.model/pro': { enable_thinking: true, reasoning_effort: 'high' } },
    })
    vi.mocked(resourcesApi.replace).mockRejectedValue(new Error('模型参数组合无效'))
    const wrapper = mount(AIProviderEditor, { props: { initial }, global })
    await flushPromises()

    await button(wrapper, '配置参数').trigger('click')
    await flushPromises()

    const thinking = wrapper.get('[aria-label="enable_thinking"]')
    await thinking.setValue(false)
    await flushPromises()
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(resourcesApi.replace).toHaveBeenCalledWith(
      'ai',
      'provider',
      expect.objectContaining({
        models: {
          'vendor.model/pro': { enable_thinking: false, reasoning_effort: 'high' },
        },
      }),
    )
    expect(wrapper.text()).toContain('模型参数组合无效')
    expect(wrapper.text()).toContain('vendor.model/pro')
    wrapper.unmount()
  })

  it('creates a channel and emits the complete server result', async () => {
    const result = config({
      id: 'created-provider',
      models: { 'vendor.model/pro': {} },
    })
    const encrypted = {
      kind: 'encrypted' as const,
      format_version: 1,
      key_id: 'key-id',
      ciphertext: 'ciphertext',
    }
    vi.mocked(resourcesApi.protectCredential).mockResolvedValue(encrypted)
    vi.mocked(resourcesApi.create).mockResolvedValue(result)
    const wrapper = mount(AIProviderEditor, { global })
    await flushPromises()

    await wrapper.get('input[placeholder="https://api.openai.com/v1"]').setValue(result.base_url)
    await wrapper.get('input[type="password"]').setValue('test-key')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(resourcesApi.create).toHaveBeenCalledWith(
      'ai',
      expect.objectContaining({ base_url: result.base_url, api_key: encrypted }),
    )
    expect(wrapper.emitted('saved')?.[0]).toEqual([result])
    wrapper.unmount()
  })

  it('blocks health checks after a saved connection changes until an explicit save', async () => {
    const initial = config()
    const saved = config({ base_url: 'https://new.example.test/v1' })
    vi.mocked(resourcesApi.replace).mockResolvedValue(saved)
    vi.mocked(resourcesApi.checkAIConnection).mockResolvedValue([])
    const wrapper = mount(AIProviderEditor, { props: { initial }, global })
    await flushPromises()

    await wrapper.get('input[placeholder="https://api.openai.com/v1"]').setValue(saved.base_url)
    expect(button(wrapper, '检查健康').attributes('disabled')).toBeDefined()
    await button(wrapper, '检查健康').trigger('click')
    expect(resourcesApi.checkAIConnection).not.toHaveBeenCalled()

    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(resourcesApi.replace).toHaveBeenCalledWith(
      'ai',
      'provider',
      expect.objectContaining({ base_url: saved.base_url }),
    )
    expect(button(wrapper, '检查健康').attributes('disabled')).toBeUndefined()

    await button(wrapper, '检查健康').trigger('click')
    await flushPromises()
    expect(resourcesApi.checkAIConnection).toHaveBeenCalledWith('provider')
    wrapper.unmount()
  })

  it('keeps health disabled when a new credential is protected but saving the changed connection fails', async () => {
    const initial = config()
    const encrypted = {
      kind: 'encrypted' as const,
      format_version: 1,
      key_id: 'key-id',
      ciphertext: 'ciphertext',
    }
    vi.mocked(resourcesApi.protectCredential).mockResolvedValue(encrypted)
    vi.mocked(resourcesApi.replace).mockRejectedValue(new Error('replace failed'))
    const wrapper = mount(AIProviderEditor, { props: { initial }, global })
    await flushPromises()

    wrapper.findComponent(ElSelect).vm.$emit('update:modelValue', 'input')
    await flushPromises()
    await wrapper.get('input[type="password"]').setValue('new-key')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(resourcesApi.protectCredential).toHaveBeenCalledWith('new-key')
    expect(resourcesApi.replace).toHaveBeenCalled()
    expect(wrapper.text()).toContain('replace failed')
    expect(button(wrapper, '检查健康').attributes('disabled')).toBeDefined()
    await button(wrapper, '检查健康').trigger('click')
    expect(resourcesApi.checkAIConnection).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('keeps invalid JSON validation active after collapsing model parameters', async () => {
    const initial = config({
      models: { 'vendor.model/pro': { extra: { valid: true } } },
    })
    const wrapper = mount(AIProviderEditor, { props: { initial }, global })
    await flushPromises()

    await button(wrapper, '配置参数').trigger('click')
    const rawValue = wrapper.get('textarea[aria-label="extra"]')
    await rawValue.setValue('{')
    await flushPromises()
    await button(wrapper, '收起参数').trigger('click')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(resourcesApi.replace).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请检查表单中的错误')
    wrapper.unmount()
  })
})
