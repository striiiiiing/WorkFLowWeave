import Ajv2020, { type ErrorObject, type ValidateFunction } from 'ajv/dist/2020'
import addFormats from 'ajv-formats'
import localize from 'ajv-i18n/localize/zh'
import type { FieldRule, ValueType } from '@/domain/parameters'
import type { JsonObject, JsonValue } from '@/types'

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

  function node(definition: JsonValue, pointer?: string): FieldRule {
    const declared =
      typeof definition === 'object' && definition !== null ? (definition as JsonObject) : {}
    const validate =
      pointer === undefined
        ? ajv.compile(definition as boolean | JsonObject)
        : ajv.getSchema(`parameters#${pointer}`)!
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
        let child: JsonValue = definition
        for (const key of path) {
          if (child === null || typeof child !== 'object' || !(key in child)) return node({})
          child = (child as JsonObject)[key]
        }
        const suffix = path.map((key) => key.replace(/~/g, '~0').replace(/\//g, '~1')).join('/')
        return node(child, pointer === undefined ? undefined : `${pointer}/${suffix}`)
      },
    }
  }
  return node(schema, '')
}
