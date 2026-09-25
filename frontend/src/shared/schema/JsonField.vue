<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { JsonObject } from '@/shared/types'
import { ParameterInput } from '@/shared/schema/parameters'
import { createFieldRule } from '@/shared/schema/schemaValidation'
const props = defineProps<{
  modelValue: JsonObject
  label: string
  prop: string | string[]
  excludedProperties?: string[]
  field?: ParameterInput
}>()
const emit = defineEmits<{ 'update:modelValue': [value: JsonObject] }>()
const field = computed(() => props.field ?? new ParameterInput(createFieldRule()))
const text = ref('')
const error = ref('')
let signature = ''
function project(value: JsonObject) {
  return Object.fromEntries(
    Object.entries(value).filter(([key]) => !props.excludedProperties?.includes(key)),
  )
}
function read(text: string) {
  return field.value.readObject(text, (value) => {
    const forbidden = Object.keys(value).filter((key) => props.excludedProperties?.includes(key))
    if (forbidden.length)
      return { ok: false, error: `请使用专用输入框填写字段：${forbidden.join('、')}` }
    const preserved = Object.fromEntries(
      Object.entries(props.modelValue).filter(([key]) => props.excludedProperties?.includes(key)),
    )
    return { ok: true, value: { ...value, ...preserved } }
  })
}
watch(
  () => project(props.modelValue),
  (value) => {
    const next = JSON.stringify(value)
    if (next === signature) return
    signature = next
    text.value = JSON.stringify(value, null, 2)
    error.value = ''
  },
  { immediate: true },
)
function validate(_rule: unknown, _value: unknown, callback: (error?: Error) => void) {
  const result = read(text.value)
  callback(result.ok ? undefined : new Error(result.error))
}
function update(value: string) {
  text.value = value
  const result = read(value)
  error.value = result.ok ? '' : result.error
  if (!result.ok) return
  signature = JSON.stringify(project(result.value as JsonObject))
  emit('update:modelValue', result.value as JsonObject)
}
defineExpose({ isValid: () => read(text.value).ok })
</script>
<template>
  <el-form-item :label="label" :error="error" :prop="prop" :rules="{ validator: validate }">
    <el-input
      :model-value="text"
      type="textarea"
      :rows="5"
      :aria-label="label"
      @update:model-value="update"
    />
  </el-form-item>
</template>
