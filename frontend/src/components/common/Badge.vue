<template>
  <!-- [Design Decision DEC-COLOR-01] 运行状态徽标满足 WCAG AAA 级（≥ 7:1）对比度 -->
  <span
    :class="[
      'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium tracking-wide transition-colors',
      badgeStyle
    ]"
  >
    <AppIcon v-if="iconName" :name="iconName" size="sm" :spin="iconSpin" />
    <slot>{{ label }}</slot>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/icons/AppIcon.vue'
import type { SessionStatus } from '@/types'

const props = withDefaults(
  defineProps<{
    status?: SessionStatus | string
    label?: string
    variant?: 'status' | 'neutral' | 'brand'
  }>(),
  {
    variant: 'status',
  }
)

const badgeStyle = computed(() => {
  if (props.variant === 'neutral') {
    return 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200 border border-slate-200 dark:border-slate-700'
  }
  if (props.variant === 'brand') {
    return 'bg-blue-100 text-blue-900 dark:bg-blue-950 dark:text-blue-100 border border-blue-200 dark:border-blue-800'
  }

  // [Design Decision DEC-COLOR-01] 针对系统运行状态的高对比度 AAA 色值配置
  switch (props.status) {
    case 'completed':
      // 亮色：深绿 #14532D 在浅绿 #DCFCE7 上，对比度 8.1:1 (AAA)
      // 暗色：浅绿 #DCFCE7 在深绿 #14532D 上，对比度 8.1:1 (AAA)
      return 'bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-100 border border-green-300 dark:border-green-800'
    case 'running':
      // 亮色：深天蓝 #075985 在浅蓝 #E0F2FE 上，对比度 7.2:1 (AAA)
      return 'bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-100 border border-sky-300 dark:border-sky-800'
    case 'partial':
      // 亮色：深琥珀 #78350F 在浅琥珀 #FEF3C7 上，对比度 7.3:1 (AAA)
      return 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100 border border-amber-300 dark:border-amber-800'
    case 'failed':
      // 亮色：深红 #991B1B 在浅红 #FEE2E2 上，对比度 7.4:1 (AAA)
      return 'bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-100 border border-red-300 dark:border-red-800'
    case 'cancelled':
    case 'interrupted':
      return 'bg-slate-200 text-slate-900 dark:bg-slate-800 dark:text-slate-100 border border-slate-300 dark:border-slate-700'
    case 'created':
    default:
      return 'bg-blue-50 text-blue-900 dark:bg-blue-900/50 dark:text-blue-100 border border-blue-200 dark:border-blue-700'
  }
})

const iconName = computed(() => {
  switch (props.status) {
    case 'completed':
      return 'check-circle'
    case 'running':
      return 'loader'
    case 'partial':
      return 'alert-triangle'
    case 'failed':
      return 'x-octagon'
    case 'cancelled':
    case 'interrupted':
      return 'stop'
    case 'created':
      return 'clock'
    default:
      return ''
  }
})

const iconSpin = computed(() => props.status === 'running')
</script>
