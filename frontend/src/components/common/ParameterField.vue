<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { JsonObject, JsonValue } from '@/types'
import JsonField from './JsonField.vue'
const props = defineProps<{
  modelValue: JsonObject
  label: string
  prop: string
  schema?: JsonObject
}>()
const emit = defineEmits<{ 'update:modelValue': [value: JsonObject] }>()
type ValueType = 'string' | 'number' | 'boolean' | 'null' | 'object' | 'array'
type Row = { key: string; enabled: boolean; type: ValueType; text: string; boolean: boolean }
const hasOwn = (value: object, key: string) => Object.prototype.hasOwnProperty.call(value, key)
const types: ValueType[] = ['string', 'number', 'boolean', 'null', 'object', 'array']
const names: Record<ValueType, string> = {
  string: '字符串',
  number: '数字',
  boolean: '布尔值',
  null: '空值',
  object: '对象',
  array: '数组',
}
const rows = ref<Row[]>([])
const raw = ref(false)
const rawField = ref<InstanceType<typeof JsonField>>()
const newKey = ref('')
const addError = ref('')
const properties = computed(() => (props.schema?.properties ?? {}) as Record<string, JsonObject>)
const required = computed(() => (props.schema?.required ?? []) as string[])
const canAdd = computed(() => props.schema?.additionalProperties !== false)
let signature = ''
function typeOf(value: JsonValue): ValueType {
  if (value === null) return 'null'
  if (Array.isArray(value)) return 'array'
  return typeof value as ValueType
}
function rule(key: string): JsonObject {
  const field = properties.value[key]
  if (field) return field
  const additional = props.schema?.additionalProperties
  return additional && typeof additional === 'object' && !Array.isArray(additional)
    ? additional
    : {}
}
function fieldFormat(key: string): string | undefined {
  const format = rule(key).format
  return typeof format === 'string' ? format : undefined
}
function isMultiEnum(key: string): boolean {
  const items = rule(key).items
  return (
    rule(key).type === 'array' &&
    !!items &&
    typeof items === 'object' &&
    !Array.isArray(items) &&
    Array.isArray((items as JsonObject).enum)
  )
}
function allowedTypes(key: string): ValueType[] {
  const field = rule(key)
  const declared = Array.isArray(field.type) ? field.type : field.type ? [field.type] : []
  if (declared.length)
    return [
      ...new Set(declared.map((type) => (type === 'integer' ? 'number' : type))),
    ] as ValueType[]
  if (Array.isArray(field.enum)) return [...new Set(field.enum.map(typeOf))]
  return types
}
function emptyValue(type: ValueType): JsonValue {
  return { string: '', number: 0, boolean: false, null: null, object: {}, array: [] }[type]
}
function initialValue(key: string): JsonValue {
  const field = rule(key)
  if ('default' in field) return field.default
  if (Array.isArray(field.enum) && field.enum.length) return field.enum[0]
  return emptyValue(allowedTypes(key)[0])
}
function makeRow(key: string, enabled: boolean, value: JsonValue): Row {
  return {
    key,
    enabled,
    type: typeOf(value),
    text: typeof value === 'string' ? value : JSON.stringify(value, null, 2),
    boolean: value === true,
  }
}
function rebuild(value: JsonObject) {
  const keys = [...new Set([...Object.keys(properties.value), ...Object.keys(value)])]
  rows.value = keys.map((key) =>
    hasOwn(value, key) ? makeRow(key, true, value[key]) : makeRow(key, false, initialValue(key)),
  )
}
watch(
  () => props.modelValue,
  (value) => {
    const next = JSON.stringify(value)
    if (next === signature) return
    signature = next
    rebuild(value)
  },
  { immediate: true, deep: true },
)
watch(
  () => props.schema,
  () => {
    const previous = new Map(rows.value.map((row) => [row.key, row]))
    rebuild(props.modelValue)
    rows.value = rows.value.map((row) => previous.get(row.key) ?? row)
  },
  { deep: true },
)
function parse(row: Row): JsonValue {
  if (row.type === 'string') return row.text
  if (row.type === 'boolean') return row.boolean
  if (row.type === 'null') return null
  const value: JsonValue = JSON.parse(row.text)
  if (typeOf(value) !== row.type || (row.type === 'number' && !Number.isFinite(value)))
    throw new Error(`请输入有效${names[row.type]}`)
  if (rule(row.key).type === 'integer' && !Number.isInteger(value)) throw new Error('请输入整数')
  return value
}
function rowError(row: Row): string {
  if (!row.enabled) return required.value.includes(row.key) ? '此字段必填' : ''
  if (!allowedTypes(row.key).includes(row.type)) return '当前值类型不符合字段声明，请调整类型'
  try {
    const value = parse(row)
    const choices = isMultiEnum(row.key)
      ? ((rule(row.key).items as JsonObject).enum as JsonValue[])
      : rule(row.key).enum
    if (isMultiEnum(row.key) && !Array.isArray(value)) return '请选择一个或多个值'
    if (
      Array.isArray(choices) &&
      (isMultiEnum(row.key)
        ? (value as JsonValue[]).some(
            (item) => !choices.some((choice) => JSON.stringify(choice) === JSON.stringify(item)),
          )
        : !choices.some((choice) => JSON.stringify(choice) === JSON.stringify(value)))
    )
      return '请选择字段声明的枚举值'
    return ''
  } catch (cause) {
    return cause instanceof Error ? cause.message : String(cause)
  }
}
const error = computed(() => {
  if (raw.value) return ''
  if (addError.value) return addError.value
  if (newKey.value) return '请添加正在填写的字段，或清空字段名'
  const row = rows.value.find((item) => rowError(item))
  return row ? `${row.key}：${rowError(row)}` : ''
})
function validate(_rule: unknown, _value: unknown, callback: (error?: Error) => void) {
  callback(error.value ? new Error(error.value) : undefined)
}
function publish() {
  // Invalid drafts stay visible and block the parent form; never save the last valid value silently.
  if (rows.value.some((row) => row.enabled && rowError(row))) return
  const value = Object.fromEntries(
    rows.value.filter((row) => row.enabled).map((row) => [row.key, parse(row)]),
  )
  signature = JSON.stringify(value)
  emit('update:modelValue', value)
}
function setType(row: Row, type: ValueType) {
  Object.assign(row, makeRow(row.key, true, emptyValue(type)))
  publish()
}
function setEnum(row: Row, text: string) {
  Object.assign(row, makeRow(row.key, true, JSON.parse(text)))
  publish()
}
function add() {
  const key = newKey.value
  if (!key) {
    addError.value = '请输入字段名'
    return
  }
  if (rows.value.some((row) => row.key === key)) {
    addError.value = '字段名重复'
    return
  }
  rows.value.push(makeRow(key, true, initialValue(key)))
  newKey.value = ''
  addError.value = ''
  publish()
}
function remove(row: Row) {
  rows.value = rows.value.filter((item) => item !== row)
  publish()
}
function toggleMode() {
  if (raw.value) {
    if (!rawField.value?.isValid()) return
    rebuild(props.modelValue)
  } else if (
    addError.value ||
    newKey.value ||
    rows.value.some((row) => row.enabled && rowError(row))
  )
    return
  raw.value = !raw.value
}
</script>
<template>
  <section class="mb-5 min-w-0" :aria-label="label">
    <div class="flex flex-wrap justify-between items-center gap-2 mb-3">
      <h3 class="font-medium">{{ label }}</h3>
      <el-button @click="toggleMode">{{ raw ? '填写参数' : '编辑 JSON' }}</el-button>
    </div>
    <p v-if="schema?.description" class="muted text-sm mb-3">{{ schema.description }}</p>
    <JsonField
      v-if="raw"
      ref="rawField"
      :model-value="modelValue"
      :label="label"
      :prop="prop"
      @update:model-value="emit('update:modelValue', $event)"
    />
    <el-form-item v-else :prop="prop" :rules="{ validator: validate }" :error="error">
      <div class="w-full min-w-0">
        <div v-for="row in rows" :key="row.key" class="border rounded p-3 mb-3 min-w-0">
          <div class="flex flex-wrap items-center gap-2 mb-2">
            <span class="mono break-all">
              {{ row.key }}{{ required.includes(row.key) ? ' *' : '' }}
            </span>
            <el-switch v-model="row.enabled" :aria-label="`设置 ${row.key}`" @change="publish" />
            <el-button v-if="!hasOwn(properties, row.key)" text @click="remove(row)">
              删除 {{ row.key }}
            </el-button>
          </div>
          <p v-if="rule(row.key).description" class="muted text-sm mb-2">
            {{ rule(row.key).description }}
          </p>
          <p v-if="!row.enabled" class="muted text-sm">
            未设置{{
              'default' in rule(row.key) ? `（默认：${JSON.stringify(rule(row.key).default)}）` : ''
            }}
          </p>
          <template v-else>
            <el-select
              v-if="isMultiEnum(row.key)"
              multiple
              :model-value="
                rowError(row)
                  ? []
                  : (JSON.parse(row.text) as JsonValue[]).map((choice) => JSON.stringify(choice))
              "
              :aria-label="row.key"
              @update:model-value="
                (value) => {
                  Object.assign(
                    row,
                    makeRow(
                      row.key,
                      true,
                      (value as string[]).map((choice) => JSON.parse(choice)),
                    ),
                  )
                  publish()
                }
              "
            >
              <el-option
                v-for="choice in (rule(row.key).items as JsonObject).enum as JsonValue[]"
                :key="JSON.stringify(choice)"
                :value="JSON.stringify(choice)"
                :label="typeof choice === 'string' ? choice : JSON.stringify(choice)"
              />
            </el-select>
            <el-select
              v-else-if="Array.isArray(rule(row.key).enum)"
              :model-value="rowError(row) ? undefined : JSON.stringify(parse(row))"
              :aria-label="row.key"
              @update:model-value="setEnum(row, $event)"
            >
              <el-option
                v-for="choice in rule(row.key).enum as JsonValue[]"
                :key="JSON.stringify(choice)"
                :value="JSON.stringify(choice)"
                :label="typeof choice === 'string' ? choice : JSON.stringify(choice)"
              />
            </el-select>
            <template v-else>
              <el-select
                :model-value="row.type"
                :aria-label="`${row.key} 类型`"
                class="mb-2"
                @update:model-value="setType(row, $event)"
              >
                <el-option
                  v-for="type in allowedTypes(row.key)"
                  :key="type"
                  :value="type"
                  :label="names[type]"
                />
              </el-select>
              <el-switch
                v-if="row.type === 'boolean'"
                v-model="row.boolean"
                :aria-label="row.key"
                @change="publish"
              />
              <span v-else-if="row.type === 'null'">null</span>
              <el-input
                v-else
                v-model="row.text"
                :type="row.type === 'object' || row.type === 'array' ? 'textarea' : 'text'"
                :placeholder="
                  fieldFormat(row.key) === 'date'
                    ? 'YYYY-MM-DD'
                    : fieldFormat(row.key) === 'uri' || fieldFormat(row.key) === 'url'
                      ? 'https://…'
                      : row.type === 'object' || row.type === 'array'
                        ? '仅此字段的 JSON 值'
                        : ''
                "
                :rows="3"
                :aria-label="row.key"
                @input="publish"
              />
            </template>
            <p v-if="rowError(row)" class="text-red-700 mt-1">{{ rowError(row) }}</p>
          </template>
        </div>
        <div v-if="canAdd" class="flex gap-2">
          <el-input
            v-model="newKey"
            :aria-label="`${label} 新字段名`"
            placeholder="字段名"
            @input="addError = ''"
            @keydown.enter.prevent="add"
          />
          <el-button @click="add">添加字段</el-button>
        </div>
        <p v-if="!rows.length && !canAdd" class="muted">没有可配置字段。</p>
      </div>
    </el-form-item>
  </section>
</template>
