<script setup lang="ts">
import { computed } from 'vue'
import { healthLabels } from '@/modules/system/public'
import type { DashboardController } from '../composables/useDashboard'
import DashboardMetricCard from './DashboardMetricCard.vue'
const props = defineProps<{ dashboard: DashboardController }>()
const metrics = computed(() => {
  const { workflows, sessions, health } = props.dashboard
  const state = (query: typeof workflows | typeof sessions | typeof health) => ({
    pending: query.pending.value,
    error: query.error.value,
    hasData: query.data.value !== undefined,
    readAt: query.readAt.value,
  })
  return [
    {
      label: '已保存工作流',
      value: workflows.data.value?.length ?? '—',
      description: '可复用的流程编排',
      ...state(workflows),
    },
    {
      label: '最近运行',
      value: sessions.data.value?.length ?? '—',
      description: '近期执行记录',
      ...state(sessions),
    },
    {
      label: '系统状态',
      value: health.data.value ? healthLabels[health.data.value.status] : '—',
      description: '后端健康检查',
      ...state(health),
    },
    {
      label: '接受新运行',
      value: health.data.value ? (health.data.value.accepting_runs ? '是' : '否') : '—',
      description: '当前任务接收状态',
      ...state(health),
    },
  ]
})
</script>
<template>
  <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
    <DashboardMetricCard v-for="metric in metrics" :key="metric.label" v-bind="metric" />
  </div>
</template>
