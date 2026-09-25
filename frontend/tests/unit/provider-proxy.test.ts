import { resourcesApiKey } from '@/modules/resources/api/dependencies'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AIProviderEditor from '@/modules/resources/ui/AIProviderEditor.vue'
import ParameterField from '@/shared/schema/ParameterField.vue'
import { resourcesApi } from '@/api/resources'
import { createResource } from '@/domain/resources'
import type { AIConfig } from '@/types'

vi.mock('@/api/resources', () => ({
  resourcesApi: { replace: vi.fn() },
}))

afterEach(() => vi.clearAllMocks())

describe('saving reactive model edits', () => {
  const initial = (): AIConfig => ({
    ...(createResource('ai') as AIConfig),
    id: 'provider',
    base_url: 'https://example.test/v1',
    models: { 'vendor/model.v1': { reasoning_effort: 'high', custom: { nested: [1, true] } } },
  })

  it('saves after adding another model without trying to structured-clone nested proxies', async () => {
    const source = initial()
    vi.mocked(resourcesApi.replace).mockImplementation(async (_kind, _id, value) =>
      JSON.parse(JSON.stringify(value)),
    )
    const wrapper = mount(AIProviderEditor, {
      props: { initial: source },
      global: { plugins: [ElementPlus], provide: { [resourcesApiKey as symbol]: resourcesApi } },
    })
    await wrapper.get('input[aria-label="模型名称"]').setValue('vendor/model.v2')
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '添加模型')!
      .trigger('click')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(resourcesApi.replace).toHaveBeenCalledWith(
      'ai',
      'provider',
      expect.objectContaining({
        models: { ...source.models, 'vendor/model.v2': {} },
      }),
    )
    expect(wrapper.emitted('saved')).toHaveLength(1)
    expect(Object.keys(source.models)).toEqual(['vendor/model.v1'])
    expect(wrapper.text()).not.toContain('could not be cloned')
    wrapper.unmount()
  })

  it('saves edited parameters without losing the other model or mutating the original resource', async () => {
    const source = initial()
    source.models.second = { custom: { keep: true } }
    vi.mocked(resourcesApi.replace).mockImplementation(async (_kind, _id, value) =>
      JSON.parse(JSON.stringify(value)),
    )
    const wrapper = mount(AIProviderEditor, {
      props: { initial: source },
      global: { plugins: [ElementPlus], provide: { [resourcesApiKey as symbol]: resourcesApi } },
    })
    wrapper.findAllComponents(ParameterField)[0].vm.$emit('update:modelValue', {
      enable_thinking: true,
      reasoning_effort: 'max',
    })
    await flushPromises()
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(resourcesApi.replace).toHaveBeenCalledWith(
      'ai',
      'provider',
      expect.objectContaining({
        models: {
          'vendor/model.v1': { enable_thinking: true, reasoning_effort: 'max' },
          second: { custom: { keep: true } },
        },
      }),
    )
    expect(wrapper.emitted('saved')).toHaveLength(1)
    expect(source.models['vendor/model.v1'].reasoning_effort).toBe('high')
    wrapper.unmount()
  })
})
