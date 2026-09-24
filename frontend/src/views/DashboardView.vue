<script setup lang="ts">
import { workflowsApi } from '@/api/workflows'
import { computed, ref } from 'vue'
import { pluginHealthRows } from '@/domain/pluginHealth'
import { runsApi } from '@/api/runs'
import { systemApi } from '@/api/system'
import { useQuery } from '@/shared/async/useQuery'
import PageHeader from '@/shared/ui/PageHeader.vue'
import SectionCard from '@/shared/ui/SectionCard.vue'
import SessionTable from '@/components/common/SessionTable.vue'

const advanced = ref(false)
const updatedAt = ref<Record<string, string>>({})

function tracked<T>(key: string, fetcher: (signal: AbortSignal) => Promise<T>) {
  return async (signal: AbortSignal) => {
    const value = await fetcher(signal)
    updatedAt.value = { ...updatedAt.value, [key]: new Date().toISOString() }
    return value
  }
}

const workflowsQuery = useQuery(
  tracked('workflows', (signal) => workflowsApi.list(signal)),
)
const sessionsQuery = useQuery(tracked('sessions', (signal) => runsApi.list({ limit: 5 }, signal)))
const pluginsQuery = useQuery(tracked('plugins', (signal) => systemApi.plugins(signal)))
const healthQuery = useQuery(tracked('health', (signal) => systemApi.health(signal)))

const workflows = workflowsQuery.data
const workflowsPending = workflowsQuery.pending
const workflowsError = workflowsQuery.error
const sessions = sessionsQuery.data
const sessionsPending = sessionsQuery.pending
const sessionsError = sessionsQuery.error
const plugins = pluginsQuery.data
const pluginsPending = pluginsQuery.pending
const pluginsError = pluginsQuery.error
const health = healthQuery.data
const healthPending = healthQuery.pending
const healthError = healthQuery.error
const healthLabels = { ready: '就绪', degraded: '部分降级', unavailable: '不可用' } as const
const pluginRows = computed(() =>
  plugins.value && health.value ? pluginHealthRows(plugins.value, health.value) : [],
)
const registeredPluginCount = computed(() => plugins.value?.length ?? '—')
const healthStatus = computed(() => (health.value ? healthLabels[health.value.status] : '—'))
const acceptingRuns = computed(() =>
  health.value ? (health.value.accepting_runs ? '是' : '否') : '—',
)

function formatUpdated(key: string) {
  const value = updatedAt.value[key]
  return value ? `上次成功读取：${new Date(value).toLocaleString('zh-CN')}` : ''
}

function staleMessage(key: string, error: string, hasData: boolean) {
  if (!error) return ''
  return hasData
    ? `${error}；以下内容来自上次成功读取（${formatUpdated(key).replace('上次成功读取：', '')}）`
    : error
}

async function refreshAll() {
  await Promise.all([
    workflowsQuery.refresh(),
    sessionsQuery.refresh(),
    pluginsQuery.refresh(),
    healthQuery.refresh(),
  ])
}
</script>
<template>
  <PageHeader title="监控总览" description="当前系统运行状况与最近执行记录">
    <el-switch v-model="advanced" active-text="高级模式" aria-label="高级模式" />
    <el-button
      :loading="workflowsPending || sessionsPending || pluginsPending || healthPending"
      @click="refreshAll"
    >
      刷新
    </el-button>
  </PageHeader>

  <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
    <el-card shadow="hover">
      <p class="muted">已保存工作流</p>
      <p class="text-3xl font-bold text-blue-600 dark:text-blue-400 my-3">
        {{ workflows?.length ?? '—' }}
      </p>
      <p class="muted text-xs">可复用的流程编排</p>
      <p v-if="workflowsPending" class="muted text-xs mt-2">正在读取</p>
      <p v-else-if="workflowsError" class="text-red-600 text-xs mt-2">
        {{ staleMessage('workflows', workflowsError, !!workflows) }}
      </p>
      <p v-else class="muted text-xs mt-2">{{ formatUpdated('workflows') }}</p>
    </el-card>
    <el-card shadow="hover">
      <p class="muted">已注册插件能力</p>
      <p class="text-3xl font-bold text-blue-600 dark:text-blue-400 my-3">
        {{ registeredPluginCount }}
      </p>
      <p class="muted text-xs">采集器与通知渠道</p>
      <p v-if="pluginsPending" class="muted text-xs mt-2">正在读取</p>
      <p v-else-if="pluginsError" class="text-red-600 text-xs mt-2">
        {{ staleMessage('plugins', pluginsError, !!plugins) }}
      </p>
      <p v-else class="muted text-xs mt-2">{{ formatUpdated('plugins') }}</p>
    </el-card>
    <el-card shadow="hover">
      <p class="muted">系统状态</p>
      <p class="text-3xl font-bold text-blue-600 dark:text-blue-400 my-3">{{ healthStatus }}</p>
      <p class="muted text-xs">后端健康检查</p>
      <p v-if="healthPending" class="muted text-xs mt-2">正在读取</p>
      <p v-else-if="healthError" class="text-red-600 text-xs mt-2">
        {{ staleMessage('health', healthError, !!health) }}
      </p>
      <p v-else class="muted text-xs mt-2">{{ formatUpdated('health') }}</p>
    </el-card>
    <el-card shadow="hover">
      <p class="muted">接受新运行</p>
      <p class="text-3xl font-bold text-blue-600 dark:text-blue-400 my-3">{{ acceptingRuns }}</p>
      <p class="muted text-xs">当前任务接收状态</p>
      <p v-if="health" class="muted text-xs mt-2">
        健康检查时间：{{ new Date(health.checked_at).toLocaleString('zh-CN') }}
      </p>
    </el-card>
  </div>

  <el-alert
    v-if="health && health.status !== 'ready'"
    :title="`系统${healthLabels[health.status]}`"
    type="warning"
    :closable="false"
  />

  <SectionCard title="最近执行历史">
    <template #actions><router-link to="/runs">查看全部历史 →</router-link></template>
    <el-alert
      v-if="sessionsError"
      :title="staleMessage('sessions', sessionsError, !!sessions)"
      type="error"
      :closable="false"
      show-icon
      class="mb-4"
    />
    <SessionTable :sessions="sessions ?? []" :loading="sessionsPending" />
  </SectionCard>

  <SectionCard
    title="插件健康状态"
    class="mt-6"
    description="显示注册诊断与受影响资源，不代表远程服务连通性。"
  >
    <el-alert
      v-if="pluginsError"
      :title="staleMessage('plugins', pluginsError, !!plugins)"
      type="error"
      :closable="false"
      show-icon
      class="mb-4"
    />
    <el-alert
      v-if="healthError"
      :title="staleMessage('health', healthError, !!health)"
      type="warning"
      :closable="false"
      show-icon
      class="mb-4"
    />
    <el-table v-if="plugins && health" :data="pluginRows" empty-text="暂无插件">
      <el-table-column prop="plugin" label="插件" />
      <el-table-column prop="kind" label="类型" />
      <el-table-column label="已注册能力">
        <template #default="{ row }">{{ row.capabilities.join('、') || '—' }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" />
      <el-table-column label="诊断与受影响资源" min-width="280">
        <template #default="{ row }">
          <span>{{ row.errors.join('；') || '—' }}</span>
          <span v-if="row.affectedResources.length" class="block text-orange-600 mt-1">
            受影响资源：{{ row.affectedResources.join('、') }}
          </span>
        </template>
      </el-table-column>
    </el-table>
    <p v-else-if="plugins && healthError" class="muted py-4">
      已读取 {{ plugins.length }} 项注册能力，系统诊断暂时不可用。
    </p>
    <p v-else-if="pluginsPending || healthPending" class="muted py-4">正在读取插件诊断</p>
    <p v-else class="muted py-4">暂无插件诊断</p>
  </SectionCard>

  <SectionCard v-if="advanced" title="组件健康状态" class="mt-6">
    <el-table v-if="health" :data="health.components">
      <el-table-column prop="component" label="组件" />
      <el-table-column prop="status" label="状态" />
      <el-table-column label="错误信息" min-width="220">
        <template #default="{ row }">{{ row.error?.message ?? '—' }}</template>
      </el-table-column>
    </el-table>
    <p v-else class="muted py-4">{{ healthError || '正在读取组件诊断' }}</p>
  </SectionCard>
</template>
