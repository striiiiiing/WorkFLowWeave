import { defineComponent, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect, type FormInstance } from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import AIModelSelect from '@/components/workflow/AIModelSelect.vue'
import type { AIConfig } from '@/types'

const config = (id: string, models: string[]): AIConfig => ({
  id,
  provider: id,
  base_url: null,
  api_key: null,
  system_prompt: '',
  models: Object.fromEntries(models.map((name) => [name, {}])),
  timeout: 600,
  retries: 5,
})

function editor(
  initial: { ai: string | null; model: string | null },
  configs: AIConfig[],
  optional = false,
) {
  const state = ref(initial)
  const form = ref<FormInstance>()
  const wrapper = mount(
    defineComponent({
      components: { AIModelSelect },
      setup: () => ({ state, form, configs, optional }),
      template:
        '<el-form ref="form" :model="state"><AIModelSelect v-model:ai="state.ai" v-model:model="state.model" :configs="configs" ai-prop="ai" model-prop="model" :optional="optional" /></el-form>',
    }),
    { global: { plugins: [ElementPlus] } },
  )
  const validate = async () => {
    await flushPromises()
    return form.value!.validate().catch(() => false)
  }
  return { state, form, wrapper, validate }
}

describe('workflow AI channel and model selection', () => {
  it('selects a configured channel model and clears the model when the channel changes', async () => {
    const { state, wrapper } = editor({ ai: null, model: null }, [
      config('openai', ['gpt-4']),
      config('other', ['gpt-4']),
    ])
    const selects = wrapper.findAllComponents(ElSelect)

    selects[0].vm.$emit('update:modelValue', 'openai')
    await flushPromises()
    selects[1].vm.$emit('update:modelValue', 'gpt-4')
    await flushPromises()
    expect(state.value).toEqual({ ai: 'openai', model: 'gpt-4' })

    selects[0].vm.$emit('update:modelValue', 'other')
    await flushPromises()
    expect(state.value).toEqual({ ai: 'other', model: null })
    wrapper.unmount()
  })

  it('shows a resource link and disables model selection when no models are configured', () => {
    const { wrapper } = editor({ ai: null, model: null }, [config('empty-channel', [])])
    const resourceLink = wrapper.get('a[href="/resources?kind=ai"]')
    expect(resourceLink.text()).toContain('前往配置供应商渠道')
    expect(resourceLink.attributes('target')).toBe('_blank')
    expect(resourceLink.attributes('rel')).toBe('noopener')
    expect(wrapper.findAllComponents(ElSelect)[1].props('disabled')).toBe(true)
    expect(wrapper.text()).toContain('现有供应商渠道均未配置模型')
    wrapper.unmount()
  })

  it('keeps invalid saved references visible and rejects them without clearing', async () => {
    const { state, wrapper, validate } = editor({ ai: 'deleted-channel', model: 'deleted-model' }, [
      config('openai', ['gpt-4']),
    ])
    await vi.waitFor(() => expect(wrapper.text()).toContain('供应商渠道不存在：deleted-channel'))
    expect(wrapper.text()).toContain('失效供应商渠道：deleted-channel')
    expect(wrapper.text()).toContain('失效渠道模型：deleted-model')
    expect(wrapper.text()).toContain('供应商渠道不存在：deleted-channel')
    expect(await validate()).toBe(false)
    expect(state.value).toEqual({ ai: 'deleted-channel', model: 'deleted-model' })
    wrapper.unmount()
  })

  it('requires both fields for optional aggregation and validates model ownership', async () => {
    const { state, wrapper, validate } = editor(
      { ai: null, model: null },
      [config('openai', ['gpt-4'])],
      true,
    )
    expect(await validate()).toBe(true)

    state.value.ai = 'openai'
    expect(await validate()).toBe(false)
    state.value.model = 'gpt-4'
    expect(await validate()).toBe(true)
    state.value.model = 'other-model'
    expect(await validate()).toBe(false)
    state.value.ai = null
    expect(await validate()).toBe(false)
    wrapper.unmount()
  })

  it('requires a channel and an owned model for analysis tasks', async () => {
    const { state, wrapper, validate } = editor({ ai: null, model: null }, [
      config('openai', ['gpt-4']),
    ])
    expect(await validate()).toBe(false)
    state.value.ai = 'openai'
    state.value.model = 'gpt-4'
    expect(await validate()).toBe(true)
    wrapper.unmount()
  })
})
