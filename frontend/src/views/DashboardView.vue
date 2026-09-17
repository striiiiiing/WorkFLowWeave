<template>
  <div class="space-y-6">
    <!-- 头部仪表盘概览 -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <div>
        <h2 class="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
          监控总览 (Dashboard)
        </h2>
        <p class="text-sm text-slate-500 dark:text-slate-400 mt-1">
          当前系统运行状况、活跃工作流执行与容量监控
        </p>
      </div>

      <div class="flex items-center gap-3">
        <Button variant="secondary" icon="rotate-ccw" @click="refreshAll">
          刷新
        </Button>
        <router-link to="/workflows/new">
          <Button icon="plus">新建工作流</Button>
        </router-link>
      </div>
    </div>

    <!-- 关键指标卡片网格 -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <Card custom-class="p-5">
        <span class="text-xs font-semibold text-slate-500 uppercase tracking-wider">活跃运行数 / 容量</span>
        <div class="mt-2 flex items-baseline gap-2">
          <span class="text-3xl font-bold text-slate-900 dark:text-slate-100">
            {{ systemStore.health?.active_runs ?? 0 }}
          </span>
          <span class="text-sm text-slate-400">
            / {{ systemStore.health?.max_concurrent_runs ?? 4 }}
          </span>
        </div>
        <p class="text-xs text-slate-400 mt-1">全局运行并发控制</p>
      </Card>

      <Card custom-class="p-5">
        <span class="text-xs font-semibold text-slate-500 uppercase tracking-wider">已保存工作流</span>
        <div class="mt-2 flex items-baseline gap-2">
          <span class="text-3xl font-bold text-blue-600 dark:text-blue-400">
            {{ workflowStore.workflows.length }}
          </span>
        </div>
        <p class="text-xs text-slate-400 mt-1">可随时触发或定时调度</p>
      </Card>

      <Card custom-class="p-5">
        <span class="text-xs font-semibold text-slate-500 uppercase tracking-wider">已注册插件能力</span>
        <div class="mt-2 flex items-baseline gap-2">
          <span class="text-3xl font-bold text-indigo-600 dark:text-indigo-400">
            {{ systemStore.plugins.length }}
          </span>
        </div>
        <p class="text-xs text-slate-400 mt-1">包含 Collector 与 Channel 扩展</p>
      </Card>

      <Card custom-class="p-5">
        <span class="text-xs font-semibold text-slate-500 uppercase tracking-wider">系统健康状态</span>
        <div class="mt-2 flex items-center gap-2">
          <span class="w-3 h-3 rounded-full bg-green-500 animate-pulse" />
          <span class="text-lg font-bold text-green-700 dark:text-green-400 uppercase">
            {{ systemStore.health?.status ?? 'HEALTHY' }}
          </span>
        </div>
        <p class="text-xs text-slate-400 mt-1">运行时间: {{ formatUptime(systemStore.health?.uptime_seconds) }}</p>
      </Card>
    </div>

    <!-- 最近执行记录列表 -->
    <Card title="最近执行历史 (Recent Sessions)" subtitle="只读 Session 视图，直接消费后端业务存档">
      <template #header-actions>
        <router-link to="/runs">
          <Button size="sm" variant="ghost">查看全部</Button>
        </router-link>
      </template>

      <div v-if="runStore.sessions.length === 0" class="p-8 text-center text-slate-400 text-sm">
        暂无运行记录
      </div>

      <div v-else class="divide-y divide-slate-100 dark:divide-slate-700/60 -mx-5 -my-2">
        <div
          v-for="session in runStore.sessions.slice(0, 5)"
          :key="session.session_id"
          class="px-5 py-3.5 flex items-center justify-between hover:bg-slate-50/80 dark:hover:bg-slate-700/30 transition-colors"
        >
          <div class="flex items-center gap-3">
            <Badge :status="session.status" />
            <div>
              <router-link
                :to="`/runs/${session.session_id}`"
                class="text-sm font-semibold font-mono text-blue-600 dark:text-blue-400 hover:underline"
              >
                {{ session.session_id }}
              </router-link>
              <div class="flex items-center gap-2 text-xs text-slate-400 mt-0.5">
                <span>所属工作流: <strong class="font-mono text-slate-600 dark:text-slate-300">{{ session.workflow_id }}</strong></span>
                <span>•</span>
                <span>阶段: {{ session.current_stage }}</span>
              </div>
            </div>
          </div>

          <div class="text-right">
            <span class="text-xs text-slate-400">{{ session.created_at }}</span>
          </div>
        </div>
      </div>
    </Card>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import Card from '@/components/common/Card.vue'
import Button from '@/components/common/Button.vue'
import Badge from '@/components/common/Badge.vue'
import { useWorkflowStore } from '@/stores/workflowStore'
import { useRunStore } from '@/stores/runStore'
import { useSystemStore } from '@/stores/systemStore'

const workflowStore = useWorkflowStore()
const runStore = useRunStore()
const systemStore = useSystemStore()

function formatUptime(seconds?: number) {
  if (!seconds) return '刚刚启动'
  const m = Math.floor(seconds / 60)
  const h = Math.floor(m / 60)
  if (h > 0) return `${h}小时 ${m % 60}分钟`
  return `${m}分钟`
}

async function refreshAll() {
  await Promise.all([
    workflowStore.fetchWorkflows(),
    runStore.fetchSessions({ limit: 10 }),
    systemStore.fetchHealth(),
    systemStore.fetchPlugins(),
  ])
}

onMounted(() => {
  refreshAll()
})
</script>
