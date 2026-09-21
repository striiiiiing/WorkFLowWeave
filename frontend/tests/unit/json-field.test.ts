/**
 * JSON 字段组件测试：挂载真实组件并输入非法 JSON，断言阻止保存、显示校验反馈，且保留此前有效对象；不启动后端。
 */
import { defineComponent, ref } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
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
    for (const [input, message] of [
      ['{invalid', 'JSON 格式不正确，请检查双引号、逗号和括号是否完整。'],
      ['{}extra', 'JSON 格式不正确，请检查双引号、逗号和括号是否完整。'],
      ['[]', '请输入 JSON 对象（用 { } 包裹），不能使用数组或单个值。'],
      ['null', '请输入 JSON 对象（用 { } 包裹），不能使用数组或单个值。'],
      ['', '请输入 JSON 对象，例如 {"name":"示例"}。'],
    ]) {
      await wrapper.find('textarea').setValue(input)
      await flushPromises()
      expect(value.value).toEqual({ enabled: true })
      expect(await form.value!.validate().catch(() => false)).toBe(false)
      await vi.waitFor(() => expect(wrapper.text()).toContain(message))
      expect(wrapper.text()).not.toMatch(/Unexpected|position|SyntaxError/)
      expect(wrapper.find('textarea').element.value).toBe(input)
    }
    await wrapper.find('textarea').setValue('{ "enabled": false }')
    await flushPromises()
    expect(await form.value!.validate()).toBe(true)
    expect(value.value).toEqual({ enabled: false })
    expect(wrapper.find('textarea').element.value).toBe('{ "enabled": false }')
    wrapper.unmount()
  })
})
