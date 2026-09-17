<template>
  <!-- [Design Decision DEC-MOTION-01] 250ms 减速平滑转场，ESC 键退出与遮罩点击 -->
  <Teleport to="body">
    <div
      v-if="modelValue"
      class="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4"
      aria-modal="true"
      role="dialog"
      @keydown.esc="$emit('update:modelValue', false)"
    >
      <!-- 遮罩背景 -->
      <div
        class="fixed inset-0 bg-slate-900/60 backdrop-blur-sm transition-opacity"
        @click="$emit('update:modelValue', false)"
      />

      <!-- 弹窗容器 -->
      <div
        :class="[
          'relative bg-white dark:bg-slate-800 rounded-xl shadow-2xl border border-slate-200 dark:border-slate-700 w-full max-h-[90vh] flex flex-col z-10 transition-all transform duration-200',
          maxWidthClass
        ]"
      >
        <!-- 弹窗头部 -->
        <div class="px-6 py-4 border-b border-slate-100 dark:border-slate-700 flex items-center justify-between">
          <h3 class="text-lg font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2">
            <AppIcon v-if="icon" :name="icon" class="text-blue-600 dark:text-blue-400" />
            {{ title }}
          </h3>
          <button
            type="button"
            class="p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 min-h-[44px] min-w-[44px] flex items-center justify-center"
            @click="$emit('update:modelValue', false)"
          >
            <AppIcon name="x" size="sm" />
          </button>
        </div>

        <!-- 弹窗内容 (滚动区) -->
        <div class="p-6 overflow-y-auto flex-1">
          <slot />
        </div>

        <!-- 弹窗底部操作 -->
        <div v-if="$slots.footer" class="px-6 py-3.5 bg-slate-50 dark:bg-slate-900/40 rounded-b-xl border-t border-slate-100 dark:border-slate-700 flex items-center justify-end gap-3">
          <slot name="footer" />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/icons/AppIcon.vue'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    title: string
    icon?: string
    maxWidth?: 'sm' | 'md' | 'lg' | 'xl' | '2xl'
  }>(),
  {
    maxWidth: 'md',
  }
)

defineEmits<{
  (e: 'update:modelValue', value: boolean): void
}>()

const maxWidthClass = computed(() => {
  switch (props.maxWidth) {
    case 'sm':
      return 'max-w-sm'
    case 'lg':
      return 'max-w-lg'
    case 'xl':
      return 'max-w-xl'
    case '2xl':
      return 'max-w-2xl'
    case 'md':
    default:
      return 'max-w-md'
  }
})
</script>
