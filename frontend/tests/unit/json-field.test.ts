import { defineComponent, ref } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ElementPlus, { type FormInstance } from 'element-plus'
import JsonField from '@/components/common/JsonField.vue'

describe('JSON field form integration', () => {
  it('blocks save on invalid draft JSON without losing the previous object', async () => {
    const form = ref<FormInstance>()
    const value = ref({ enabled: true })
    const wrapper = mount(
      defineComponent({
        components: { JsonField },
        setup: () => ({ form, value }),
        template:
          '<el-form ref="form" :model="{ options: value }"><JsonField v-model="value" prop="options" label="参数" /></el-form>',
      }),
      { global: { plugins: [ElementPlus] } },
    )
    await wrapper.find('textarea').setValue('{invalid')
    await flushPromises()
    expect(value.value).toEqual({ enabled: true })
    expect(await form.value!.validate().catch(() => false)).toBe(false)
    await wrapper.find('textarea').setValue('{ "enabled": false }')
    await flushPromises()
    expect(await form.value!.validate()).toBe(true)
    expect(value.value).toEqual({ enabled: false })
    expect(wrapper.find('textarea').element.value).toBe('{ "enabled": false }')
    wrapper.unmount()
  })
})
