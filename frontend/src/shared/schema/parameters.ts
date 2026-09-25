import equal from 'fast-deep-equal'
import type { JsonObject, JsonValue } from '@/shared/types'

export type ValueType = 'string' | 'number' | 'boolean' | 'null' | 'object' | 'array'
export interface ValueDraft {
  id: string
  type: ValueType
  text: string
  boolean: boolean
  items: ValueDraft[]
}
export type InputResult = { ok: true; value: JsonValue } | { ok: false; error: string }

/** Validation and reference resolution belong to the injected schema adapter. */
export interface FieldRule {
  readonly definition: JsonObject
  readonly allowed: boolean
  validate(value: JsonValue, inputType?: ValueType): string
  at(...path: string[]): FieldRule
}

const typeNames: Record<ValueType, string> = {
  string: '字符串',
  number: '数字',
  boolean: '布尔值',
  null: '空值',
  object: '对象',
  array: '数组',
}
const emptyValues: Record<ValueType, JsonValue> = {
  string: '',
  number: 0,
  boolean: false,
  null: null,
  object: {},
  array: [],
}

/** Schema-bound field metadata, editable drafts and immutable list operations. */
export class ParameterInput {
  private readonly children = new Map<string, ParameterInput>()

  constructor(private readonly rule: FieldRule) {}

  private valueType(value: JsonValue): ValueType {
    return value === null ? 'null' : Array.isArray(value) ? 'array' : (typeof value as ValueType)
  }

  get schema() {
    return this.rule.definition
  }
  get types(): ValueType[] {
    const declared = Array.isArray(this.schema.type)
      ? this.schema.type
      : this.schema.type
        ? [this.schema.type]
        : []
    if (declared.length)
      return [
        ...new Set(declared.map((type) => (type === 'integer' ? 'number' : type))),
      ] as ValueType[]
    if (Array.isArray(this.schema.enum))
      return [...new Set(this.schema.enum.map((value) => this.valueType(value)))]
    return Object.keys(typeNames) as ValueType[]
  }
  get typeOptions() {
    return this.types.map((value) => ({ value, label: typeNames[value] }))
  }
  get choices() {
    return Array.isArray(this.schema.enum)
      ? this.schema.enum.map((value) => ({
          value: JSON.stringify(value),
          label: typeof value === 'string' ? value : JSON.stringify(value),
        }))
      : undefined
  }
  get repeatable() {
    return this.schema.uniqueItems !== true
  }
  get initialValue(): JsonValue {
    if ('default' in this.schema) return this.schema.default
    if (Array.isArray(this.schema.enum) && this.schema.enum.length) return this.schema.enum[0]
    return emptyValues[this.types[0]]
  }
  label(name: string): string {
    return this.types.length === 1 ? `${name}（${typeNames[this.types[0]]}）` : name
  }
  private child(...path: string[]): ParameterInput {
    const key = JSON.stringify(path)
    if (!this.children.has(key)) this.children.set(key, new ParameterInput(this.rule.at(...path)))
    return this.children.get(key)!
  }
  property(name: string): ParameterInput {
    const properties = this.schema.properties as JsonObject | undefined
    return properties && Object.prototype.hasOwnProperty.call(properties, name)
      ? this.child('properties', name)
      : this.child('additionalProperties')
  }
  item(index: number): ParameterInput {
    return Array.isArray(this.schema.prefixItems) && index < this.schema.prefixItems.length
      ? this.child('prefixItems', String(index))
      : this.child('items')
  }
  create(value: JsonValue = this.initialValue): ValueDraft {
    const type = this.valueType(value)
    return {
      id: crypto.randomUUID(),
      type,
      text:
        type === 'array' ? '' : typeof value === 'string' ? value : JSON.stringify(value, null, 2),
      boolean: value === true,
      items: Array.isArray(value) ? value.map((item, index) => this.item(index).create(item)) : [],
    }
  }
  private parse(text: string, type: 'number' | 'object'): InputResult {
    const integer = this.schema.type === 'integer'
    if (!text.trim())
      return {
        ok: false,
        error:
          type === 'object'
            ? '请输入 JSON 对象，例如 {"name":"示例"}。'
            : integer
              ? '请输入整数，例如 10。'
              : '请输入数字。',
      }
    try {
      return { ok: true, value: JSON.parse(text) }
    } catch (cause) {
      if (!(cause instanceof SyntaxError)) throw cause
      return {
        ok: false,
        error:
          type === 'object'
            ? 'JSON 格式不正确，请检查双引号、逗号和括号是否完整。'
            : integer
              ? '请输入有效整数，例如 10，不能混入文字。'
              : '请输入有效数字，例如 10 或 3.5，不能混入文字。',
      }
    }
  }
  validate(value: JsonValue, inputType?: ValueType): InputResult {
    const error = this.rule.validate(value, inputType)
    return error ? { ok: false, error } : { ok: true, value }
  }
  read(draft: ValueDraft): InputResult {
    let value: JsonValue
    switch (draft.type) {
      case 'array': {
        const items: JsonValue[] = []
        for (const [index, item] of draft.items.entries()) {
          const result = this.item(index).read(item)
          if (!result.ok) return { ok: false, error: `第 ${index + 1} 项：${result.error}` }
          items.push(result.value)
        }
        value = items
        break
      }
      case 'string':
        value = draft.text
        break
      case 'boolean':
        value = draft.boolean
        break
      case 'null':
        value = null
        break
      default: {
        const result = this.parse(draft.text, draft.type)
        if (!result.ok) return result
        value = result.value
      }
    }
    return this.validate(value, draft.type)
  }
  readObject(text: string, restore?: (value: JsonObject) => InputResult): InputResult {
    const parsed = this.parse(text, 'object')
    if (!parsed.ok) return parsed
    const value = parsed.value
    if (!restore || value === null || Array.isArray(value) || typeof value !== 'object')
      return this.validate(value, 'object')
    const restored = restore(value)
    return restored.ok ? this.validate(restored.value, 'object') : restored
  }
  error(draft: ValueDraft): string {
    const result = this.read(draft)
    return result.ok ? '' : result.error
  }
  setType(draft: ValueDraft, type: ValueType): ValueDraft {
    return { ...this.create(emptyValues[type]), id: draft.id }
  }
  select(draft: ValueDraft, value: string): ValueDraft {
    return { ...this.create(JSON.parse(value)), id: draft.id }
  }
  selected(draft: ValueDraft): string | undefined {
    const result = this.read(draft)
    if (!result.ok || !Array.isArray(this.schema.enum)) return undefined
    return JSON.stringify(this.schema.enum.find((choice) => equal(choice, result.value)))
  }
  atLimit(draft: ValueDraft): boolean {
    return (
      !this.item(draft.items.length).rule.allowed ||
      (typeof this.schema.maxItems === 'number' && draft.items.length >= this.schema.maxItems)
    )
  }
  private nextItem(draft: ValueDraft): JsonValue | undefined {
    const field = this.item(draft.items.length)
    if (this.repeatable || !Array.isArray(field.schema.enum)) return field.initialValue
    const selected = draft.items.map((item, index) => this.item(index).read(item))
    return field.schema.enum.find(
      (candidate) => !selected.some((result) => result.ok && equal(result.value, candidate)),
    )
  }
  canAdd(draft: ValueDraft): boolean {
    return !this.atLimit(draft) && this.nextItem(draft) !== undefined
  }
  add(draft: ValueDraft): ValueDraft {
    const value = this.nextItem(draft)
    if (this.atLimit(draft) || value === undefined) return draft
    return { ...draft, items: [...draft.items, this.item(draft.items.length).create(value)] }
  }
  duplicate(draft: ValueDraft, index: number): ValueDraft {
    const result = this.item(index).read(draft.items[index])
    if (!this.repeatable || this.atLimit(draft) || !result.ok) return draft
    const items = [...draft.items]
    items.splice(index + 1, 0, this.item(index + 1).create(result.value))
    return { ...draft, items }
  }
  replace(draft: ValueDraft, index: number, value: ValueDraft): ValueDraft {
    return {
      ...draft,
      items: draft.items.map((item, position) => (position === index ? value : item)),
    }
  }
  remove(draft: ValueDraft, index: number): ValueDraft {
    return { ...draft, items: draft.items.filter((_item, position) => position !== index) }
  }
  move(draft: ValueDraft, index: number, offset: number): ValueDraft {
    const items = [...draft.items]
    const target = index + offset
    if (target < 0 || target >= items.length) return draft
    ;[items[index], items[target]] = [items[target], items[index]]
    return { ...draft, items }
  }
}
