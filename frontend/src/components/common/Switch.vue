<template>
  <label class="inline-flex items-center cursor-pointer select-none min-h-[44px]">
    <div class="relative">
      <input
        type="checkbox"
        class="sr-only"
        :checked="modelValue"
        :disabled="disabled"
        @change="$emit('update:modelValue', ($event.target as HTMLInputElement).checked)"
      />
      <!-- 背景槽 -->
      <div
        :class="[
          'w-11 h-6 rounded-full transition-colors',
          modelValue ? 'bg-blue-600 dark:bg-blue-500' : 'bg-slate-300 dark:bg-slate-700',
          disabled ? 'opacity-50 cursor-not-allowed' : ''
        ]"
      />
      <!-- 滑块圆点 -->
      <div
        :class="[
          'absolute left-1 top-1 bg-white w-4 h-4 rounded-full transition-transform',
          modelValue ? 'translate-x-5' : 'translate-x-0'
        ]"
      />
    </div>
    <span v-if="label" class="ml-3 text-sm font-medium text-slate-700 dark:text-slate-300">
      {{ label }}
    </span>
  </label>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    modelValue: boolean
    label?: string
    disabled?: boolean
  }>(),
  {
    disabled: false,
  }
)

defineEmits<{
  (e: 'update:modelValue', value: boolean): void
}>()
</script>
