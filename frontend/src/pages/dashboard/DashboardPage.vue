<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { SystemHealthAlert } from '@/modules/system/public'
import PageHeader from '@/shared/ui/PageHeader.vue'
import DashboardMetrics from './ui/DashboardMetrics.vue'
import RecentRunsPanel from './ui/RecentRunsPanel.vue'
import { useDashboard } from './composables/useDashboard'
const router = useRouter()
const dashboard = useDashboard()
const pending = computed(
  () =>
    dashboard.workflows.pending.value ||
    dashboard.sessions.pending.value ||
    dashboard.health.pending.value,
)
function openRun(id: string) {
  void router.push({ name: 'run-detail', params: { id } })
}
</script>
<template>
  <PageHeader title="监控总览" description="当前系统运行状况与最近执行记录">
    <el-button :loading="pending" @click="dashboard.refreshAll">刷新</el-button>
  </PageHeader>
  <DashboardMetrics :dashboard="dashboard" />
  <SystemHealthAlert :health="dashboard.health.data.value" />
  <RecentRunsPanel
    :query="dashboard.sessions"
    @open="openRun"
    @all="router.push({ name: 'runs' })"
  />
</template>
