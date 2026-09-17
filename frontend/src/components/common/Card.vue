<template>
  <!-- [Design Decision DEC-COLOR-02 & DEC-LAYOUT-01] 统一容器卡片设计 -->
  <div
    :class="[
      'bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm transition-shadow',
      hover ? 'hover:shadow-md' : '',
      customClass
    ]"
  >
    <div v-if="$slots.header || title" class="px-5 py-4 border-b border-slate-100 dark:border-slate-700/60 flex items-center justify-between">
      <div>
        <h3 v-if="title" class="text-base font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2">
          <AppIcon v-if="icon" :name="icon" class="text-blue-600 dark:text-blue-400" size="sm" />
          {{ title }}
        </h3>
        <p v-if="subtitle" class="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
          {{ subtitle }}
        </p>
      </div>
      <slot name="header-actions" />
    </div>

    <div :class="['p-5', bodyClass]">
      <slot />
    </div>

    <div v-if="$slots.footer" class="px-5 py-3.5 bg-slate-50 dark:bg-slate-900/40 rounded-b-xl border-t border-slate-100 dark:border-slate-700/60 flex items-center justify-between">
      <slot name="footer" />
    </div>
  </div>
</template>

<script setup lang="ts">
import AppIcon from '@/components/icons/AppIcon.vue'

withDefaults(
  defineProps<{
    title?: string
    subtitle?: string
    icon?: string
    hover?: boolean
    customClass?: string
    bodyClass?: string
  }>(),
  {
    hover: false,
    customClass: '',
    bodyClass: '',
  }
)
</script>
