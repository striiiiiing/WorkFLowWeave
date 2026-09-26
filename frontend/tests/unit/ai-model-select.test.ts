import { defineComponent, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect, type FormInstance } from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import AIModelSelect from '@/modules/workflows/ui/AIModelSelect.vue'
import type { AIConfig } from '@/modules/resources/public'

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
        '<el-form ref="form" :model="state"><AIModelSelect :ai="state.ai" :model="state.model" :configs="configs" ai-prop="ai" model-prop="model" :optional="optional" @selection="(ai, model) => { state.ai = ai; state.model = model }" /></el-form>',
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
  it('updates the channel and model in one selection', async () => {
    const { state, wrapper } = editor({ ai: null, model: null }, [
      config('openai', ['gpt-4']),
      config('other', ['gpt-4']),
    ])
    const select = wrapper.getComponent(ElSelect)
    select.vm.$emit('update:modelValue', JSON.stringify(['openai', 'gpt-4']))
    await flushPromises()
    expect(state.value).toEqual({ ai: 'openai', model: 'gpt-4' })

    select.vm.$emit('update:modelValue', JSON.stringify(['other', 'gpt-4']))
    await flushPromises()
    expect(state.value).toEqual({ ai: 'other', model: 'gpt-4' })
    wrapper.unmount()
  })

  it('shows a resource link when no models are configured', () => {
    const { wrapper } = editor({ ai: null, model: null }, [config('empty-channel', [])])
    const resourceLink = wrapper.get('a[href="/resources?kind=ai"]')
    expect(resourceLink.text()).toContain('配置供应商渠道模型')
    expect(resourceLink.attributes('target')).toBe('_blank')
    expect(resourceLink.attributes('rel')).toBe('noopener')
    expect(wrapper.findAllComponents(ElSelect)).toHaveLength(1)
    wrapper.unmount()
  })

  it('keeps invalid saved references visible and rejects them without clearing', async () => {
    const { state, wrapper, validate } = editor({ ai: 'deleted-channel', model: 'deleted-model' }, [
      config('openai', ['gpt-4']),
    ])
    await vi.waitFor(() =>
      expect(wrapper.text()).toContain('deleted-channel / deleted-model（不可用）'),
    )
    expect(wrapper.text()).toContain('所选模型已不可用')
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
