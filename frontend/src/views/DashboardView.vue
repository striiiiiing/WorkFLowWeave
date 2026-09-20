<script setup lang="ts">
import { computed, ref } from 'vue'
import { pluginHealthRows } from '@/domain/pluginHealth'
import { resourcesApi } from '@/api/resources'
import { runsApi } from '@/api/runs'
import { systemApi } from '@/api/system'
import { useQuery } from '@/composables/useQuery'
import PageHeader from '@/components/common/PageHeader.vue'
import SectionCard from '@/components/common/SectionCard.vue'
import SessionTable from '@/components/common/SessionTable.vue'
const advanced = ref(false)
const { data, pending, error, refresh } = useQuery(async (signal) => {
  const [workflows, sessions, plugins, health] = await Promise.all([
    resourcesApi.list('workflows', signal),
    runsApi.list({ limit: 5 }, signal),
    systemApi.plugins(signal),
    systemApi.health(signal),
  ])
  return { workflows, sessions, plugins, health, pluginRows: pluginHealthRows(plugins, health) }
})
const healthLabels = { ready: '就绪', degraded: '部分降级', unavailable: '不可用' }
const metrics = computed(() => [
  { title: '已保存工作流', value: data.value?.workflows.length ?? '—', note: '可复用的流程编排' },
  {
    title: '已注册插件能力',
    value: data.value?.plugins.length ?? '—',
    note: 'Collector / Channel',
  },
  {
    title: '系统状态',
    value: data.value ? healthLabels[data.value.health.status] : '—',
    note: '后端健康检查',
  },
  {
    title: '接受新运行',
    value: data.value ? (data.value.health.accepting_runs ? '是' : '否') : '—',
    note: '当前任务接收状态',
  },
])
</script>
<template>
  <PageHeader title="监控总览" description="当前系统运行状况与最近执行记录">
    <el-switch v-model="advanced" active-text="高级模式" aria-label="高级模式" />
    <el-button :loading="pending" @click="refresh">刷新</el-button>
  </PageHeader>
  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
  <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
    <el-card v-for="metric in metrics" :key="metric.title" shadow="hover">
      <p class="muted">{{ metric.title }}</p>
      <p class="text-3xl font-bold text-blue-600 dark:text-blue-400 my-3">{{ metric.value }}</p>
      <p class="muted text-xs">{{ metric.note }}</p>
    </el-card>
  </div>
  <el-alert
    v-if="data && data.health.status !== 'ready'"
    :title="`系统${healthLabels[data.health.status]}`"
    type="warning"
    :closable="false"
  />
  <SectionCard title="最近执行历史">
    <template #actions><router-link to="/runs">查看全部历史 →</router-link></template>
    <SessionTable :sessions="data?.sessions ?? []" :loading="pending" />
  </SectionCard>
  <SectionCard
    v-if="data"
    title="插件健康状态"
    class="mt-6"
    description="按插件类型和归属展示注册与发现诊断；不代表远程服务连通性。"
  >
    <el-alert
      v-if="data.health.components.find((item) => item.component === 'plugins')?.error"
      title="插件存在诊断，部分注册状态待确认；可在高级模式查看系统组件诊断。"
      type="warning"
      :closable="false"
      show-icon
      class="mb-4"
    />
    <el-table :data="data.pluginRows" empty-text="暂无插件">
      <el-table-column prop="plugin" label="插件" />
      <el-table-column prop="kind" label="类型" />
      <el-table-column label="已注册能力">
        <template #default="{ row }">{{ row.capabilities.join('、') || '—' }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" />
      <el-table-column label="错误信息" min-width="220">
        <template #default="{ row }">{{ row.errors.join('；') || '—' }}</template>
      </el-table-column>
    </el-table>
  </SectionCard>
  <SectionCard v-if="data && advanced" title="组件健康状态" class="mt-6">
    <el-table :data="data.health.components">
      <el-table-column prop="component" label="组件" />
      <el-table-column prop="status" label="状态" />
      <el-table-column label="错误信息" min-width="220">
        <template #default="{ row }">{{ row.error?.message ?? '—' }}</template>
      </el-table-column>
    </el-table>
  </SectionCard>
</template>
