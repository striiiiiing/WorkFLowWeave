<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { JsonObject } from '@/shared/types'
import { ParameterInput } from '@/shared/schema/parameters'
import { createFieldRule } from '@/shared/schema/schemaValidation'
const props = defineProps<{
  modelValue: JsonObject
  label: string
  prop: string | string[]
  field?: ParameterInput
}>()
const emit = defineEmits<{ 'update:modelValue': [value: JsonObject] }>()
const field = computed(() => props.field ?? new ParameterInput(createFieldRule()))
const text = ref('')
const error = ref('')
let signature = ''
watch(
  () => props.modelValue,
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
  const result = field.value.readObject(text.value)
  callback(result.ok ? undefined : new Error(result.error))
}
function update(value: string) {
  text.value = value
  const result = field.value.readObject(value)
  error.value = result.ok ? '' : result.error
  if (!result.ok) return
  signature = JSON.stringify(result.value)
  emit('update:modelValue', result.value as JsonObject)
}
defineExpose({ isValid: () => field.value.readObject(text.value).ok })
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
