<template>
  <!-- [Design Decision DEC-ICON-01 & DEC-ICON-02] 统一图标系统：规范视框 (24x24)、1.75px 圆角线性描边、光学平衡 -->
  <svg
    :class="[
      'inline-block shrink-0 transition-transform',
      sizeClass,
      customClass,
      opticalAlignmentClass,
      spin ? 'animate-spin' : ''
    ]"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <!-- 对象类图标 (Objects) -->
    <g v-if="name === 'database'">
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </g>

    <g v-else-if="name === 'bot' || name === 'cpu'">
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <rect x="9" y="9" width="6" height="6" />
      <path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3" />
    </g>

    <g v-else-if="name === 'mail'">
      <rect x="2" y="4" width="20" height="16" rx="2" />
      <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
    </g>

    <g v-else-if="name === 'key'">
      <circle cx="7.5" cy="15.5" r="4.5" />
      <path d="m21 3-9.5 9.5M15.5 7.5l3 3M18.5 4.5l2 2" />
    </g>

    <g v-else-if="name === 'workflow'">
      <rect x="3" y="3" width="6" height="6" rx="1" />
      <rect x="15" y="3" width="6" height="6" rx="1" />
      <rect x="9" y="15" width="6" height="6" rx="1" />
      <path d="M6 9v3a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V9M12 14v1" />
    </g>

    <!-- 动作类图标 (Actions) -->
    <g v-else-if="name === 'play'">
      <polygon points="5 3 19 12 5 21 5 3" fill="currentColor" />
    </g>

    <g v-else-if="name === 'rotate-ccw'">
      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
      <path d="M3 3v5h5" />
    </g>

    <g v-else-if="name === 'stop'">
      <circle cx="12" cy="12" r="9" />
      <rect x="9" y="9" width="6" height="6" fill="currentColor" />
    </g>

    <g v-else-if="name === 'trash'">
      <path d="M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
    </g>

    <g v-else-if="name === 'edit'">
      <path d="M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
    </g>

    <g v-else-if="name === 'plus'">
      <path d="M12 5v14M5 12h14" />
    </g>

    <g v-else-if="name === 'chevron-down'">
      <path d="m6 9 6 6 6-6" />
    </g>

    <g v-else-if="name === 'chevron-up'">
      <path d="m18 15-6-6-6 6" />
    </g>

    <g v-else-if="name === 'menu'">
      <line x1="4" x2="20" y1="12" y2="12" />
      <line x1="4" x2="20" y1="6" y2="6" />
      <line x1="4" x2="20" y1="18" y2="18" />
    </g>

    <g v-else-if="name === 'x'">
      <path d="M18 6 6 18M6 6l12 12" />
    </g>

    <g v-else-if="name === 'copy'">
      <rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
      <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
    </g>

    <!-- 状态类图标 (States) -->
    <g v-else-if="name === 'check-circle'">
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
      <polyline points="22 4 12 14.01 9 11.01" />
    </g>

    <g v-else-if="name === 'loader'">
      <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </g>

    <g v-else-if="name === 'alert-triangle'">
      <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
      <line x1="12" x2="12" y1="9" y2="13" />
      <line x1="12" x2="12.01" y1="17" y2="17" />
    </g>

    <g v-else-if="name === 'x-octagon'">
      <polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2" />
      <line x1="15" x2="9" y1="9" y2="15" />
      <line x1="9" x2="15" y1="9" y2="15" />
    </g>

    <g v-else-if="name === 'clock'">
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </g>

    <g v-else-if="name === 'help-circle'">
      <circle cx="12" cy="12" r="10" />
      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
      <line x1="12" x2="12.01" y1="17" y2="17" />
    </g>

    <!-- 默认占位 -->
    <g v-else>
      <circle cx="12" cy="12" r="10" />
    </g>
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    name: string
    size?: 'sm' | 'md' | 'lg' | 'xl'
    strokeWidth?: number
    customClass?: string
    spin?: boolean
  }>(),
  {
    size: 'md',
    strokeWidth: 1.75,
    customClass: '',
    spin: false,
  }
)

const sizeClass = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'w-4 h-4'
    case 'lg':
      return 'w-6 h-6'
    case 'xl':
      return 'w-8 h-8'
    case 'md':
    default:
      return 'w-5 h-5'
  }
})

// [Design Decision DEC-ICON-02] 光学平衡微调，修正不对称图形的视觉中心
const opticalAlignmentClass = computed(() => {
  if (props.name === 'play') return 'translate-x-[1px]'
  return ''
})
</script>
