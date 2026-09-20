import { defineComponent, ref } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus, { type FormInstance } from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import ParameterField from '@/components/common/ParameterField.vue'
import type { JsonObject } from '@/types'

function editor(initial: JsonObject, schema?: JsonObject) {
  const value = ref(initial)
  const form = ref<FormInstance>()
  const wrapper = mount(
    defineComponent({
      components: { ParameterField },
      setup: () => ({ value, schema, form }),
      template:
        '<el-form ref="form" :model="{ options: value }"><ParameterField v-model="value" label="参数" prop="options" :schema="schema" /></el-form>',
    }),
    { global: { plugins: [ElementPlus] } },
  )
  const valid = async () => {
    await flushPromises()
    return form.value!.validate().catch(() => false)
  }
  const mode = () =>
    wrapper.findAll('button').find((item) => ['编辑 JSON', '填写参数'].includes(item.text()))!
  return { value, wrapper, valid, mode }
}

describe('top-level parameter forms', () => {
  it('renders JSON types and blocks invalid object or numeric drafts without discarding them on mode switch', async () => {
    const { value, wrapper, valid, mode } = editor({
      text: 'hello',
      count: 2,
      enabled: true,
      empty: null,
      nested: { keep: ['x'] },
      records: [1, 2],
    })
    expect(wrapper.findAll('textarea')).toHaveLength(2)
    await wrapper.get('textarea[aria-label="nested"]').setValue('{bad')
    expect(await valid()).toBe(false)
    await mode().trigger('click')
    expect(mode().text()).toBe('编辑 JSON')
    expect(value.value.nested).toEqual({ keep: ['x'] })
    await wrapper.get('textarea[aria-label="nested"]').setValue('{"keep":["changed"]}')
    await wrapper.get('input[aria-label="count"]').setValue('2junk')
    expect(await valid()).toBe(false)
    await wrapper.get('input[aria-label="count"]').setValue('3.5')
    expect(await valid()).toBe(true)
    expect(value.value).toEqual({
      text: 'hello',
      count: 3.5,
      enabled: true,
      empty: null,
      nested: { keep: ['changed'] },
      records: [1, 2],
    })
    wrapper.unmount()
  })

  it('shows declared optional fields without saving defaults and preserves explicit false', async () => {
    const { value, wrapper, valid } = editor(
      {},
      {
        type: 'object',
        additionalProperties: false,
        properties: { enabled: { type: 'boolean', default: true, description: 'flag' } },
      },
    )
    expect(wrapper.text()).toContain('enabled')
    expect(wrapper.text()).toContain('默认：true')
    expect(value.value).toEqual({})
    await wrapper.get('[aria-label="设置 enabled"]').trigger('click')
    await flushPromises()
    expect(value.value).toEqual({ enabled: true })
    await wrapper.get('[aria-label="enabled"]').trigger('click')
    expect(await valid()).toBe(true)
    expect(value.value).toEqual({ enabled: false })
    await wrapper.get('[aria-label="设置 enabled"]').trigger('click')
    expect(value.value).toEqual({})
    wrapper.unmount()
  })

  it('opens whole JSON only explicitly and cannot bypass an invalid JSON draft', async () => {
    const { wrapper, value, valid, mode } = editor({ enabled: true })
    expect(wrapper.find('textarea').exists()).toBe(false)
    await mode().trigger('click')
    await wrapper.get('textarea').setValue('{broken')
    expect(await valid()).toBe(false)
    await mode().trigger('click')
    expect(mode().text()).toBe('填写参数')
    await wrapper.get('textarea').setValue('{"enabled":false,"array":[null]}')
    expect(await valid()).toBe(true)
    await mode().trigger('click')
    expect(value.value).toEqual({ enabled: false, array: [null] })
    expect(wrapper.get('textarea[aria-label="array"]').element.value).toContain('null')
    wrapper.unmount()
  })

  it('allows raw editing of incomplete required fields while preserving other typed values', async () => {
    const { wrapper, value, valid, mode } = editor(
      {},
      {
        type: 'object',
        required: ['account'],
        additionalProperties: false,
        properties: { account: { type: 'string' }, count: { type: 'number' } },
      },
    )
    await wrapper.get('[aria-label="设置 count"]').trigger('click')
    await wrapper.get('input[aria-label="count"]').setValue('7')
    expect(await valid()).toBe(false)
    await mode().trigger('click')
    expect(mode().text()).toBe('填写参数')
    expect(value.value).toEqual({ count: 7 })
    await wrapper.get('textarea').setValue('{"account":"configured","count":7}')
    await mode().trigger('click')
    expect(await valid()).toBe(true)
    wrapper.unmount()
  })

  it('initializes dynamic model fields as objects and rejects duplicate keys', async () => {
    const { wrapper, value, valid } = editor(
      {},
      { type: 'object', additionalProperties: { type: 'object' } },
    )
    const name = wrapper.get('input[aria-label="参数 新字段名"]')
    await name.setValue('my-model')
    await wrapper
      .findAll('button')
      .find((item) => item.text() === '添加字段')!
      .trigger('click')
    expect(value.value).toEqual({ 'my-model': {} })
    await name.setValue('my-model')
    await wrapper
      .findAll('button')
      .find((item) => item.text() === '添加字段')!
      .trigger('click')
    expect(await valid()).toBe(false)
    await vi.waitFor(() => expect(wrapper.text()).toContain('字段名重复'))
    expect(value.value).toEqual({ 'my-model': {} })
    wrapper.unmount()
  })
})
