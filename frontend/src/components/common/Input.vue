<template>
  <div class="w-full">
    <!-- [Design Decision DEC-TYPO-01 & DEC-TYPO-02] 标签与表单排版 -->
    <label v-if="label" class="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1.5">
      {{ label }}
      <span v-if="required" class="text-red-500">*</span>
    </label>

    <div class="relative">
      <input
        v-if="as !== 'textarea' && as !== 'select'"
        :type="type"
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled"
        :readonly="readonly"
        :class="[
          'w-full px-3 py-2 text-sm rounded-lg border bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 transition-colors focus:outline-none focus:ring-2 disabled:bg-slate-100 dark:disabled:bg-slate-900 disabled:cursor-not-allowed min-h-[44px]',
          mono ? 'font-mono text-xs' : '',
          error
            ? 'border-red-500 focus:ring-red-400'
            : 'border-slate-300 dark:border-slate-600 focus:ring-blue-500 dark:focus:ring-blue-400'
        ]"
        @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      />

      <textarea
        v-else-if="as === 'textarea'"
        :value="modelValue"
        :placeholder="placeholder"
        :rows="rows || 4"
        :disabled="disabled"
        :readonly="readonly"
        :class="[
          'w-full px-3 py-2 text-sm rounded-lg border bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 transition-colors focus:outline-none focus:ring-2 disabled:bg-slate-100 dark:disabled:bg-slate-900 disabled:cursor-not-allowed',
          mono ? 'font-mono text-xs' : '',
          error
            ? 'border-red-500 focus:ring-red-400'
            : 'border-slate-300 dark:border-slate-600 focus:ring-blue-500 dark:focus:ring-blue-400'
        ]"
        @input="$emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
      />
    </div>

    <!-- 字段错误提示 (AAA 级别深红) -->
    <p v-if="error" class="mt-1 text-xs text-red-600 dark:text-red-400 font-medium">
      {{ error }}
    </p>
    <p v-else-if="hint" class="mt-1 text-xs text-slate-500 dark:text-slate-400">
      {{ hint }}
    </p>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    modelValue: string | number
    label?: string
    placeholder?: string
    type?: string
    as?: 'input' | 'textarea' | 'select'
    rows?: number
    disabled?: boolean
    readonly?: boolean
    required?: boolean
    error?: string
    hint?: string
    mono?: boolean
  }>(),
  {
    type: 'text',
    as: 'input',
    disabled: false,
    readonly: false,
    required: false,
    mono: false,
  }
)

defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()
</script>
