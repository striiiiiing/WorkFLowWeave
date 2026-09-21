import { defineComponent, ref } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus, { ElSelect, type FormInstance } from 'element-plus'
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
    expect(wrapper.findAll('textarea')).toHaveLength(1)
    expect(wrapper.find('textarea[aria-label="records"]').exists()).toBe(false)
    await wrapper.get('textarea[aria-label="nested"]').setValue('{bad')
    expect(await valid()).toBe(false)
    expect(wrapper.text()).toContain('JSON 格式不正确，请检查双引号、逗号和括号是否完整。')
    expect(wrapper.text()).not.toMatch(/Unexpected|position|SyntaxError/)
    await mode().trigger('click')
    expect(mode().text()).toBe('编辑 JSON')
    expect(value.value.nested).toEqual({ keep: ['x'] })
    await wrapper.get('textarea[aria-label="nested"]').setValue('{"keep":["changed"]}')
    await wrapper.get('input[aria-label="count"]').setValue('2junk')
    expect(await valid()).toBe(false)
    expect(wrapper.text()).toContain('请输入有效数字，例如 10 或 3.5，不能混入文字。')
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
    await vi.waitFor(() =>
      expect(wrapper.text()).toContain('JSON 格式不正确，请检查双引号、逗号和括号是否完整。'),
    )
    expect(wrapper.text()).not.toMatch(/Unexpected|position|SyntaxError/)
    await mode().trigger('click')
    expect(mode().text()).toBe('填写参数')
    await wrapper.get('textarea').setValue('{"enabled":false,"array":[null]}')
    expect(await valid()).toBe(true)
    await mode().trigger('click')
    expect(value.value).toEqual({ enabled: false, array: [null] })
    expect(wrapper.get('[aria-label="array 列表"]').text()).toContain('null')
    expect(wrapper.find('textarea[aria-label="array"]').exists()).toBe(false)
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

  it('uses schema constraints in both typed controls and JSON mode', async () => {
    const { wrapper, value, valid, mode } = editor(
      { limit: 10 },
      { properties: { limit: { type: 'integer', minimum: 1, maximum: 1000 } } },
    )
    await wrapper.get('input[aria-label="limit"]').setValue('1001')
    expect(await valid()).toBe(false)
    expect(value.value.limit).toBe(10)
    expect(wrapper.text()).toContain('<= 1000')
    await wrapper.get('input[aria-label="limit"]').setValue('1000')
    expect(await valid()).toBe(true)
    await mode().trigger('click')
    await wrapper.get('textarea').setValue('{"limit":0}')
    expect(await valid()).toBe(false)
    expect(value.value.limit).toBe(1000)
    await mode().trigger('click')
    expect(mode().text()).toBe('填写参数')
    expect(wrapper.get('textarea').element.value).toBe('{"limit":0}')
    await wrapper.get('textarea').setValue('{"limit":1}')
    expect(await valid()).toBe(true)
    await mode().trigger('click')
    expect(value.value.limit).toBe(1)
    wrapper.unmount()
  })

  it('shows fixed types as text while retaining type choices for union and custom fields', async () => {
    const { wrapper, value, valid } = editor(
      { limit: 10, name: 'source', enabled: true, nullable: null, custom: 3 },
      {
        properties: {
          limit: { type: 'integer' },
          name: { type: 'string' },
          enabled: { type: 'boolean' },
          nullable: { type: ['string', 'null'] },
        },
      },
    )
    for (const [key, label] of Object.entries({
      limit: '数字',
      name: '字符串',
      enabled: '布尔值',
    })) {
      expect(wrapper.findAll('span').some((span) => span.text() === `${key}（${label}）`)).toBe(
        true,
      )
      expect(wrapper.find(`[aria-label="${key} 类型"]`).exists()).toBe(false)
    }
    const selectors = wrapper.findAllComponents(ElSelect)
    expect(selectors.map((select) => select.props('ariaLabel'))).toEqual([
      'nullable 类型',
      'custom 类型',
    ])
    selectors[0].vm.$emit('update:modelValue', 'string')
    await flushPromises()
    await wrapper.get('input[aria-label="nullable"]').setValue('chosen')
    await wrapper.get('input[aria-label="limit"]').setValue('2.5')
    expect(await valid()).toBe(false)
    await wrapper.get('input[aria-label="limit"]').setValue('12')
    expect(await valid()).toBe(true)
    expect(value.value).toMatchObject({ limit: 12, nullable: 'chosen' })
    wrapper.unmount()
  })

  it('explains invalid numeric input in Chinese and retains the draft until corrected', async () => {
    const { wrapper, value, valid, mode } = editor(
      { limit: 10 },
      { properties: { limit: { type: 'integer' } } },
    )
    const input = wrapper.get('input[aria-label="limit"]')
    for (const [text, message] of [
      ['12a', '请输入有效整数，例如 10，不能混入文字。'],
      ['', '请输入整数，例如 10。'],
      ['2.5', '请输入整数，不能包含小数。'],
      ['1e309', '数字过大，请减小数值。'],
    ]) {
      await input.setValue(text)
      expect(await valid()).toBe(false)
      await vi.waitFor(() => expect(wrapper.text()).toContain(`limit：${message}`))
      expect(wrapper.text()).not.toMatch(/Unexpected|position|SyntaxError/)
      expect(value.value.limit).toBe(10)
      await mode().trigger('click')
      expect(mode().text()).toBe('编辑 JSON')
      expect(input.element.value).toBe(text)
    }
    await input.setValue('12')
    expect(await valid()).toBe(true)
    expect(value.value.limit).toBe(12)
    expect(wrapper.text()).not.toContain('请输入')
    wrapper.unmount()
  })

  it('adds repeated enum selections and reorders or removes a specific occurrence', async () => {
    const { wrapper, value, valid, mode } = editor(
      { stages: ['collect', 'analyze'] },
      { properties: { stages: { type: 'array', items: { enum: ['collect', 'analyze'] } } } },
    )
    expect(wrapper.findAll('textarea')).toHaveLength(0)
    expect(wrapper.text()).toContain('stages（数组）')
    expect(wrapper.text()).toContain('第 1 项（字符串）')
    await wrapper.get('[aria-label="添加 stages 项目"]').trigger('click')
    expect(value.value.stages).toEqual(['collect', 'analyze', 'collect'])
    await wrapper.get('[aria-label="上移 stages 第 3 项"]').trigger('click')
    expect(value.value.stages).toEqual(['collect', 'collect', 'analyze'])
    await wrapper.get('[aria-label="删除 stages 第 1 项"]').trigger('click')
    expect(value.value.stages).toEqual(['collect', 'analyze'])
    await wrapper.get('[aria-label="重复添加 stages 第 2 项"]').trigger('click')
    expect(value.value.stages).toEqual(['collect', 'analyze', 'analyze'])
    wrapper.findAllComponents(ElSelect)[2].vm.$emit('update:modelValue', '"collect"')
    await flushPromises()
    expect(value.value.stages).toEqual(['collect', 'analyze', 'collect'])
    expect(await valid()).toBe(true)
    await mode().trigger('click')
    await mode().trigger('click')
    expect(value.value.stages).toEqual(['collect', 'analyze', 'collect'])
    expect(wrapper.findAllComponents(ElSelect)).toHaveLength(3)
    wrapper.unmount()
  })

  it('enforces unique arrays and length limits without silently discarding invalid selections', async () => {
    const { wrapper, value, valid } = editor(
      { fields: ['message'] },
      {
        properties: {
          fields: {
            type: 'array',
            items: { enum: ['message', 'level'] },
            uniqueItems: true,
            minItems: 1,
            maxItems: 2,
          },
        },
      },
    )
    await wrapper.get('[aria-label="添加 fields 项目"]').trigger('click')
    expect(value.value.fields).toEqual(['message', 'level'])
    expect(wrapper.get('[aria-label="添加 fields 项目"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[aria-label="重复添加 fields 第 1 项"]').exists()).toBe(false)
    wrapper.findAllComponents(ElSelect)[1].vm.$emit('update:modelValue', '"message"')
    await flushPromises()
    expect(await valid()).toBe(false)
    expect(wrapper.text()).toContain('此列表不允许重复项')
    expect(wrapper.findAllComponents(ElSelect)[1].props('modelValue')).toBe('"message"')
    expect(value.value.fields).toEqual(['message', 'level'])
    await wrapper.get('[aria-label="删除 fields 第 2 项"]').trigger('click')
    expect(await valid()).toBe(true)
    await wrapper.get('[aria-label="删除 fields 第 1 项"]').trigger('click')
    expect(await valid()).toBe(false)
    expect(wrapper.text()).toContain('至少添加 1 项')
    await wrapper.get('[aria-label="添加 fields 项目"]').trigger('click')
    expect(await valid()).toBe(true)
    wrapper.unmount()
  })

  it('edits arrays of numbers and nested arrays with typed items and preserves invalid drafts', async () => {
    const { wrapper, value, valid, mode } = editor(
      { values: [[1]] },
      {
        properties: {
          values: { type: 'array', items: { type: 'array', items: { type: 'integer' } } },
        },
      },
    )
    expect(wrapper.findAll('textarea')).toHaveLength(0)
    await wrapper.get('[aria-label="添加 values 第 1 项 项目"]').trigger('click')
    const input = wrapper.get('input[aria-label="values 第 1 项 第 2 项"]')
    await input.setValue('2bad')
    expect(await valid()).toBe(false)
    expect(wrapper.text()).toContain('第 1 项：第 2 项：请输入有效整数')
    await mode().trigger('click')
    expect(mode().text()).toBe('编辑 JSON')
    expect(input.element.value).toBe('2bad')
    await input.setValue('2.5')
    expect(await valid()).toBe(false)
    expect(wrapper.text()).toContain('请输入整数')
    await input.setValue('2')
    expect(await valid()).toBe(true)
    expect(value.value.values).toEqual([[1, 2]])
    wrapper.unmount()
  })

  it('initializes empty optional arrays only when enabled and supports repeated free-text items', async () => {
    const { wrapper, value, valid } = editor(
      {},
      {
        properties: { tags: { type: 'array', items: { type: 'string' } } },
      },
    )
    expect(value.value).toEqual({})
    await wrapper.get('[aria-label="设置 tags"]').trigger('click')
    expect(value.value).toEqual({ tags: [] })
    await wrapper.get('[aria-label="添加 tags 项目"]').trigger('click')
    await wrapper.get('input[aria-label="tags 第 1 项"]').setValue('tag')
    await wrapper.get('[aria-label="重复添加 tags 第 1 项"]').trigger('click')
    expect(value.value.tags).toEqual(['tag', 'tag'])
    expect(await valid()).toBe(true)
    await wrapper.get('[aria-label="设置 tags"]').trigger('click')
    expect(value.value).toEqual({})
    wrapper.unmount()
  })

  it('detects duplicate objects regardless of key order and lets users repair loaded type mismatches', async () => {
    const { wrapper, value, valid } = editor(
      {
        records: [
          { a: 1, b: 2 },
          { b: 2, a: 1 },
        ],
        limit: 'bad',
      },
      {
        properties: {
          records: { type: 'array', items: { type: 'object' }, uniqueItems: true },
          limit: { type: 'integer' },
        },
      },
    )
    expect(await valid()).toBe(false)
    expect(wrapper.text()).toContain('此列表不允许重复项')
    await wrapper.get('[aria-label="删除 records 第 2 项"]').trigger('click')
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '按声明类型重新填写')!
      .trigger('click')
    await wrapper.get('input[aria-label="limit"]').setValue('5')
    expect(await valid()).toBe(true)
    expect(value.value).toEqual({ records: [{ a: 1, b: 2 }], limit: 5 })
    wrapper.unmount()
  })
})
