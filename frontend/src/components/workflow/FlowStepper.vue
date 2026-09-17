<template>
  <!-- [Design Decision DEC-LAYOUT-01] 垂直流式阶梯包装器组件 (Vertical Flow Stepper) -->
  <div class="relative pl-8 sm:pl-10 space-y-6">
    <!-- 贯穿全程的垂直连接线 -->
    <div
      class="absolute left-3.5 sm:left-4.5 top-3 bottom-3 w-0.5 bg-slate-200 dark:bg-slate-700"
      aria-hidden="true"
    />

    <slot />
  </div>
</template>

<script setup lang="ts">
// [Design Decision DEC-LAYOUT-01] 为无画布的竖向卡片流提供视觉连续性
</script>
