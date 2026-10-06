import { describe, expect, it } from 'vitest'
import { createFieldRule } from '@/shared/schema/schemaValidation'
import { ParameterInput } from '@/shared/schema/parameters'
import type { JsonObject } from '@/shared/types'

describe('JSON Schema validation used by parameter controls', () => {
  it('uses referenced enum, arrays and nullable types as controls without weakening validation', () => {
    const root = new ParameterInput(
      createFieldRule({
        $defs: {
          mode: { type: 'string', enum: ['fast', 'full'] },
          options: {
            type: 'object',
            properties: {
              modes: { type: 'array', items: { $ref: '#/$defs/mode' }, uniqueItems: true },
            },
          },
        },
        allOf: [{ $ref: '#/$defs/options' }],
        properties: { limit: { anyOf: [{ type: 'integer', minimum: 1 }, { type: 'null' }] } },
      }),
    )
    expect(root.property('modes').types).toEqual(['array'])
    expect(
      root
        .property('modes')
        .item(0)
        .choices?.map((item) => item.label),
    ).toEqual(['fast', 'full'])
    expect(root.property('modes').validate(['fast', 'fast']).ok).toBe(false)
    expect(root.property('limit').types).toEqual(['number', 'null'])
    expect(root.property('limit').validate(0).ok).toBe(false)
    expect(root.property('limit').validate(null).ok).toBe(true)
  })

  it('keeps local references rooted and reports the failing field in Chinese', () => {
    const rule = createFieldRule({
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      type: 'object',
      $defs: { limit: { type: 'integer', minimum: 1, maximum: 1000 } },
      properties: { 'a/b~c': { $ref: '#/$defs/limit', 'x-workflowweave-workflow': true } },
    })
    const field = rule.at('properties', 'a/b~c')
    expect(field.validate(3)).toBe('')
    expect(field.validate(0)).toContain('>= 1')
    expect(field.validate(1001)).toContain('<= 1000')
    expect(field.validate(1.5)).toContain('请输入整数')
    expect(rule.validate({ 'a/b~c': 0 })).toContain('a/b~c：')
  })

  it('uses schema formats, string constraints and nullable unions', () => {
    const rule = createFieldRule({
      properties: {
        address: { type: 'string', format: 'email' },
        after: { type: ['string', 'null'], format: 'date-time' },
        name: { type: 'string', minLength: 2, pattern: '^[a-z]+$' },
      },
    })
    expect(rule.validate({ address: 'bad' })).toContain('有效的邮箱地址')
    expect(rule.validate({ after: 'yesterday' })).toContain('带时区的时间')
    expect(rule.validate({ name: 'a' })).not.toBe('')
    expect(rule.validate({ name: 'ABC' })).not.toBe('')
    expect(rule.validate({ address: 'test@example.com', after: null, name: 'ok' })).toBe('')
  })

  it('validates cross-field conditions and JSON editing against the same root rule', () => {
    const field = new ParameterInput(
      createFieldRule({
        type: 'object',
        properties: { username: { type: 'string' }, password: { type: 'string' } },
        if: { required: ['username'] },
        then: { required: ['password'] },
      }),
    )
    const invalid = field.readObject('{"username":"user"}')
    expect(invalid).toEqual({ ok: false, error: '请填写必填字段「password」' })
    expect(field.readObject('{"username":"user","password":"test"}').ok).toBe(true)
  })

  it('never inserts defaults, coerces values or discards unknown properties', () => {
    const rule = createFieldRule({
      type: 'object',
      additionalProperties: false,
      properties: { limit: { type: 'integer', default: 10 } },
    })
    const value: JsonObject = {}
    expect(rule.validate(value)).toBe('')
    expect(value).toEqual({})
    value.limit = '10'
    expect(rule.validate(value)).not.toBe('')
    expect(value.limit).toBe('10')
    delete value.limit
    value.extra = true
    expect(rule.validate(value)).not.toBe('')
    expect(value.extra).toBe(true)
  })

  it('validates tuple items and recursive references without copying schema definitions', () => {
    const rule = createFieldRule({
      $defs: {
        tree: {
          type: 'object',
          properties: { value: { type: 'integer' }, child: { $ref: '#/$defs/tree' } },
        },
      },
      properties: {
        tree: { $ref: '#/$defs/tree' },
        tuple: {
          type: 'array',
          prefixItems: [{ type: 'string' }, { type: 'integer' }],
          items: false,
        },
      },
    })
    expect(rule.validate({ tree: { value: 1, child: { value: 2 } }, tuple: ['a', 1] })).toBe('')
    expect(rule.validate({ tree: { child: { value: 'bad' } } })).toContain('tree：child：value：')
    expect(rule.validate({ tuple: ['a', 1, 2] })).not.toBe('')
    const tuple = new ParameterInput(rule.at('properties', 'tuple'))
    expect(tuple.item(1).label('第二项')).toBe('第二项（数字）')
    const draft = tuple.create(['a', 1])
    expect(tuple.canAdd(draft)).toBe(false)
    expect(tuple.add(draft)).toBe(draft)
    expect(tuple.item(2).error(tuple.item(2).create(2))).toBe('此字段或项目不允许设置，请删除。')
  })

  it('rejects non-numeric JSON literals and overflow even in a custom numeric control', () => {
    const field = new ParameterInput(createFieldRule({}))
    const draft = field.create(1)
    for (const text of ['"2"', 'null', 'false', '{}', '[]', '1e309', '2junk']) {
      expect(field.read({ ...draft, text }).ok, text).toBe(false)
    }
    expect(field.read({ ...draft, text: '-2.5e2' })).toEqual({ ok: true, value: -250 })
  })
})
