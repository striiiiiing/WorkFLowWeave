import Ajv2020, { type ErrorObject, type ValidateFunction } from 'ajv/dist/2020'
import addFormats from 'ajv-formats'
import localize from 'ajv-i18n/localize/zh'
import type { FieldRule, ValueType } from '@/shared/schema/parameters'
import type { JsonObject, JsonValue } from '@/shared/types'

function message(error: ErrorObject, value: JsonValue): string {
  const { keyword, params } = error
  if (keyword === 'type') {
    if (value === Infinity || value === -Infinity) return '数字过大，请减小数值。'
    const names: Record<string, string> = {
      integer: '请输入整数，不能包含小数。',
      number: '请输入有效数字，例如 10 或 3.5，不能混入文字。',
      object: '请输入 JSON 对象（用 { } 包裹），不能使用数组或单个值。',
      string: '请填写字符串。',
      boolean: '请选择是或否。',
      array: '请使用列表添加项目。',
      null: '此字段只能为空值。',
    }
    if (names[params.type]) return names[params.type]
  }
  if (keyword === 'uniqueItems') return '此列表不允许重复项'
  if (keyword === 'minItems') return `至少添加 ${params.limit} 项`
  if (keyword === 'maxItems') return `最多添加 ${params.limit} 项`
  if (keyword === 'enum') return '请选择字段声明的枚举值'
  if (keyword === 'false schema') return '此字段或项目不允许设置，请删除。'
  if (keyword === 'required') return `请填写必填字段「${params.missingProperty}」`
  if (keyword === 'format') {
    const formats: Record<string, string> = {
      email: '邮箱地址',
      uri: '完整网址',
      url: '完整网址',
      date: '日期，例如 2026-09-21',
      'date-time': '带时区的时间，例如 2026-09-21T10:00:00+08:00',
    }
    return `请输入有效的${formats[params.format] ?? params.format}。`
  }
  localize([error])
  return error.message!
}

function validationError(validate: ValidateFunction, value: JsonValue): string {
  if (validate(value)) return ''
  const error = validate.errors![0]
  const path = error.instancePath
    .split('/')
    .slice(1)
    .map((part) => part.replace(/~1/g, '/').replace(/~0/g, '~'))
  const prefix = path
    .map((part) => (/^\d+$/.test(part) ? `第 ${Number(part) + 1} 项` : part))
    .join('：')
  return `${prefix ? `${prefix}：` : ''}${message(error, value)}`
}

/** Compile inside the root document so field validators retain their $defs/$ref context. */
export function createFieldRule(schema: JsonObject = { type: 'object' }): FieldRule {
  // Match the backend's 2020-12 dialect, including application annotations and unions.
  // Ajv must not coerce values, insert defaults or remove unknown properties.
  const ajv = new Ajv2020({ strict: false, strictNumbers: true })
  addFormats(ajv)
  ajv.addSchema(schema, 'parameters')
  const typeChecks = new Map<ValueType, ValidateFunction>()

  function contextual(value: JsonValue): JsonValue {
    if (Array.isArray(value)) return value.map(contextual)
    if (value === null || typeof value !== 'object') return value
    return Object.fromEntries(
      Object.entries(value).map(([key, child]) => [
        key,
        key === '$ref' && typeof child === 'string' && child.startsWith('#')
          ? `parameters${child}`
          : contextual(child),
      ]),
    )
  }
  function reference(ref: string): JsonValue {
    if (!ref.startsWith('#/')) throw new Error(`不支持的字段引用：${ref}`)
    let value: JsonValue = schema
    for (const key of ref
      .slice(2)
      .split('/')
      .map((part) => part.replace(/~1/g, '/').replace(/~0/g, '~'))) {
      if (!value || typeof value !== 'object' || !(key in value))
        throw new Error(`找不到字段引用：${ref}`)
      value = (value as JsonObject)[key]
    }
    return value
  }
  function types(value: JsonObject): string[] {
    if (typeof value.type === 'string') return [value.type]
    if (Array.isArray(value.type)) return value.type as string[]
    const choices = Array.isArray(value.enum) ? value.enum : 'const' in value ? [value.const] : []
    return [
      ...new Set(
        choices.map((item) =>
          item === null ? 'null' : Array.isArray(item) ? 'array' : typeof item,
        ),
      ),
    ]
  }
  function merge(left: JsonObject, right: JsonObject): JsonObject {
    const result = { ...left, ...right }
    if (left.properties && right.properties) {
      const a = left.properties as JsonObject,
        b = right.properties as JsonObject
      result.properties = { ...a, ...b }
      for (const key of Object.keys(a))
        if (key in b) result.properties[key] = { allOf: [a[key], b[key]] }
    }
    if (Array.isArray(left.required) && Array.isArray(right.required))
      result.required = [...new Set([...left.required, ...right.required])]
    if (left.additionalProperties === false) result.additionalProperties = false
    const a = types(left),
      b = types(right)
    if (a.length && b.length)
      result.type = a.flatMap((type) =>
        b.includes(type)
          ? [type]
          : type === 'integer' && b.includes('number')
            ? ['integer']
            : type === 'number' && b.includes('integer')
              ? ['integer']
              : [],
      )
    if (Array.isArray(left.enum) && Array.isArray(right.enum))
      result.enum = left.enum.filter((v) =>
        (right.enum as JsonValue[]).some((other) => JSON.stringify(v) === JSON.stringify(other)),
      )
    return result
  }
  // Resolve only the current node; recursive schemas remain lazy through at().
  function presentation(value: JsonValue, seen = new Set<string>()): JsonObject {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
    let result: JsonObject = { ...value }
    if (typeof value.$ref === 'string' && !seen.has(value.$ref)) {
      result = merge(presentation(reference(value.$ref), new Set([...seen, value.$ref])), result)
    }
    if (Array.isArray(value.allOf))
      for (const part of value.allOf) result = merge(presentation(part, seen), result)
    const union = value.anyOf ?? value.oneOf
    if (Array.isArray(union)) {
      const branches = union.map((part) => presentation(part, seen))
      const declaredTypes = branches.map(types)
      if (declaredTypes.every((part) => part.length))
        result.type = [...new Set(declaredTypes.flat())]
      const concrete = branches.filter((part) => !types(part).every((type) => type === 'null'))
      if (concrete.length === 1) result = { ...concrete[0], ...result }
      if (
        branches.every(
          (part) => Array.isArray(part.enum) || 'const' in part || part.type === 'null',
        )
      ) {
        result.enum = branches.flatMap((part) =>
          Array.isArray(part.enum) ? part.enum : 'const' in part ? [part.const] : [null],
        )
      }
    }
    if ('const' in result) result.enum = [result.const]
    return result
  }
  function node(definition: JsonValue): FieldRule {
    const declared = presentation(definition)
    const validate =
      definition === schema
        ? ajv.getSchema('parameters')!
        : ajv.compile(contextual(definition) as boolean | JsonObject)
    return {
      definition: declared,
      allowed: definition !== false,
      validate(value, inputType) {
        const error = validationError(validate, value)
        if (error || !inputType) return error
        if (!typeChecks.has(inputType)) typeChecks.set(inputType, ajv.compile({ type: inputType }))
        return validationError(typeChecks.get(inputType)!, value)
      },
      at(...path) {
        let child: JsonValue = declared
        for (const key of path) {
          if (child === null || typeof child !== 'object' || !(key in child)) return node({})
          child = (child as JsonObject)[key]
        }
        return node(child)
      },
    }
  }
  return node(schema)
}
