<template>
  <!-- [Design Decision DEC-LAYOUT-02 & DEC-MOTION-01] 最小 44px 触控目标、平滑微动效反馈与 WCAG AA 对比度 -->
  <button
    :type="type"
    :disabled="disabled || loading"
    :class="[
      'inline-flex items-center justify-center font-medium rounded-lg transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed select-none min-h-[44px] min-w-[44px]',
      sizeStyles,
      variantStyles,
      customClass
    ]"
    @click="$emit('click', $event)"
  >
    <AppIcon v-if="loading" name="loader" :spin="true" class="mr-2" size="sm" />
    <AppIcon v-else-if="icon" :name="icon" class="mr-2" size="sm" />
    <slot />
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/icons/AppIcon.vue'

const props = withDefaults(
  defineProps<{
    type?: 'button' | 'submit' | 'reset'
    variant?: 'primary' | 'secondary' | 'danger' | 'ghost'
    size?: 'sm' | 'md' | 'lg'
    disabled?: boolean
    loading?: boolean
    icon?: string
    customClass?: string
  }>(),
  {
    type: 'button',
    variant: 'primary',
    size: 'md',
    disabled: false,
    loading: false,
    customClass: '',
  }
)

defineEmits<{
  (e: 'click', event: MouseEvent): void
}>()

const sizeStyles = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'px-3 py-1.5 text-xs'
    case 'lg':
      return 'px-5 py-3 text-base'
    case 'md':
    default:
      return 'px-4 py-2 text-sm'
  }
})

const variantStyles = computed(() => {
  switch (props.variant) {
    case 'secondary':
      return 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 border border-slate-300 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-700 focus-visible:ring-slate-400'
    case 'danger':
      return 'bg-red-600 hover:bg-red-700 text-white focus-visible:ring-red-500 shadow-sm'
    case 'ghost':
      return 'text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 focus-visible:ring-slate-400'
    case 'primary':
    default:
      return 'bg-blue-600 hover:bg-blue-700 text-white focus-visible:ring-blue-500 shadow-sm'
  }
})
</script>
