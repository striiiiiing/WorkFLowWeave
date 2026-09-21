<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { JsonObject, JsonValue } from '@/types'
import { ParameterInput, type ValueDraft } from '@/domain/parameters'
import { createFieldRule } from '@/adapters/schemaValidation'
import JsonField from './JsonField.vue'
import ParameterValue from './ParameterValue.vue'
const props = defineProps<{
  modelValue: JsonObject
  label: string
  prop: string | string[]
  schema?: JsonObject
}>()
const emit = defineEmits<{ 'update:modelValue': [value: JsonObject] }>()
type Row = { key: string; enabled: boolean; draft: ValueDraft }
const hasOwn = (value: object, key: string) => Object.prototype.hasOwnProperty.call(value, key)
const rows = ref<Row[]>([])
const raw = ref(false)
const rawField = ref<InstanceType<typeof JsonField>>()
const newKey = ref('')
const addError = ref('')
const field = computed(() => new ParameterInput(createFieldRule(props.schema)))
const properties = computed(() => (props.schema?.properties ?? {}) as Record<string, JsonObject>)
const required = computed(() => (props.schema?.required ?? []) as string[])
const canAdd = computed(() => props.schema?.additionalProperties !== false)
let signature = ''
function makeRow(key: string, enabled: boolean, value: JsonValue): Row {
  return { key, enabled, draft: field.value.property(key).create(value) }
}
function rebuild(value: JsonObject) {
  const keys = [...new Set([...Object.keys(properties.value), ...Object.keys(value)])]
  rows.value = keys.map((key) =>
    hasOwn(value, key)
      ? makeRow(key, true, value[key])
      : makeRow(key, false, field.value.property(key).initialValue),
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
function rowError(row: Row): string {
  return row.enabled ? field.value.property(row.key).error(row.draft) : ''
}
const parsed = computed(() => {
  const entries: [string, JsonValue][] = []
  for (const row of rows.value.filter((row) => row.enabled)) {
    const result = field.value.property(row.key).read(row.draft)
    if (!result.ok) return { ok: false as const, error: `${row.key}：${result.error}` }
    entries.push([row.key, result.value])
  }
  return { ok: true as const, value: Object.fromEntries(entries) }
})
const error = computed(() => {
  if (raw.value) return ''
  if (addError.value) return addError.value
  if (newKey.value) return '请添加正在填写的字段，或清空字段名'
  if (!parsed.value.ok) return parsed.value.error
  const result = field.value.validate(parsed.value.value)
  return result.ok ? '' : result.error
})
function validate(_rule: unknown, _value: unknown, callback: (error?: Error) => void) {
  callback(error.value ? new Error(error.value) : undefined)
}
function publish() {
  // Invalid drafts stay visible and block the parent form; never save the last valid value silently.
  if (!parsed.value.ok) return
  const value = parsed.value.value
  signature = JSON.stringify(value)
  emit('update:modelValue', value)
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
  rows.value.push(makeRow(key, true, field.value.property(key).initialValue))
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
  } else if (addError.value || newKey.value || !parsed.value.ok) return
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
      :field="field"
      @update:model-value="emit('update:modelValue', $event)"
    />
    <el-form-item v-else :prop="prop" :rules="{ validator: validate }" :error="error">
      <div class="w-full min-w-0">
        <div v-for="row in rows" :key="row.key" class="border rounded p-3 mb-3 min-w-0">
          <div class="flex flex-wrap items-center gap-2 mb-2">
            <span class="mono break-all">
              {{ field.property(row.key).label(row.key)
              }}{{ required.includes(row.key) ? ' *' : '' }}
            </span>
            <el-switch v-model="row.enabled" :aria-label="`设置 ${row.key}`" @change="publish" />
            <el-button v-if="!hasOwn(properties, row.key)" text @click="remove(row)">
              删除 {{ row.key }}
            </el-button>
          </div>
          <p v-if="field.property(row.key).schema.description" class="muted text-sm mb-2">
            {{ field.property(row.key).schema.description }}
          </p>
          <p v-if="!row.enabled" class="muted text-sm">
            未设置{{
              'default' in field.property(row.key).schema
                ? `（默认：${JSON.stringify(field.property(row.key).schema.default)}）`
                : ''
            }}
          </p>
          <template v-else>
            <ParameterValue
              v-model="row.draft"
              :field="field.property(row.key)"
              :label="row.key"
              @update:model-value="publish"
            />
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
