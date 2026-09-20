<script setup lang="ts">
import { ref, watch } from 'vue'
import type { JsonObject } from '@/types'
const props = defineProps<{ modelValue: JsonObject; label: string; prop: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: JsonObject] }>()
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
  callback(error.value ? new Error(error.value) : undefined)
}
function update(value: string) {
  text.value = value
  try {
    const parsed: unknown = JSON.parse(value)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
      throw new Error('请输入 JSON 对象')
    error.value = ''
    signature = JSON.stringify(parsed)
    emit('update:modelValue', parsed as JsonObject)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}
defineExpose({ isValid: () => !error.value })
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
