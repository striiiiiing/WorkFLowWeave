<template>
  <div class="space-y-6">
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <div>
        <h2 class="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
          运行历史与执行管理 (Runs)
        </h2>
        <p class="text-sm text-slate-500 dark:text-slate-400 mt-1">
          只读展示由 LangGraph 运行时节点维护的独立业务 Session 存储
        </p>
      </div>

      <Button variant="secondary" icon="rotate-ccw" @click="fetchList">
        刷新
      </Button>
    </div>

    <!-- 筛选工具栏 -->
    <div class="flex flex-wrap items-center gap-3 p-4 bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700">
      <div class="w-48">
        <input
          v-model="filterWorkflowId"
          type="text"
          placeholder="按工作流 ID 过滤..."
          class="w-full px-3 py-1.5 text-xs rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 min-h-[44px]"
          @keydown.enter="fetchList"
        />
      </div>

      <Button size="sm" @click="fetchList">筛选</Button>
      <Button v-if="filterWorkflowId" size="sm" variant="ghost" @click="filterWorkflowId = ''; fetchList()">
        清除
      </Button>
    </div>

    <!-- 列表展示 -->
    <Card>
      <div v-if="runStore.loading" class="p-12 text-center text-slate-400">
        <AppIcon name="loader" :spin="true" class="mx-auto mb-2" size="lg" />
        <span>加载执行历史中...</span>
      </div>

      <div v-else-if="runStore.sessions.length === 0" class="p-12 text-center text-slate-400 text-sm">
        未找到匹配的运行记录
      </div>

      <div v-else class="overflow-x-auto -m-5">
        <table class="w-full text-left border-collapse text-xs">
          <thead>
            <tr class="bg-slate-50 dark:bg-slate-900/60 border-b border-slate-200 dark:border-slate-700 text-slate-500">
              <th class="py-3 px-4 font-semibold">Session ID</th>
              <th class="py-3 px-4 font-semibold">所属工作流</th>
              <th class="py-3 px-4 font-semibold">状态</th>
              <th class="py-3 px-4 font-semibold">当前阶段</th>
              <th class="py-3 px-4 font-semibold">业务版本</th>
              <th class="py-3 px-4 font-semibold">创建时间</th>
              <th class="py-3 px-4 font-semibold text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 dark:divide-slate-700/60">
            <tr
              v-for="session in runStore.sessions"
              :key="session.session_id"
              class="hover:bg-slate-50/80 dark:hover:bg-slate-700/30 transition-colors"
            >
              <td class="py-3 px-4 font-mono font-bold text-blue-600 dark:text-blue-400">
                <router-link :to="`/runs/${session.session_id}`" class="hover:underline">
                  {{ session.session_id }}
                </router-link>
              </td>
              <td class="py-3 px-4 font-mono">{{ session.workflow_id }}</td>
              <td class="py-3 px-4">
                <!-- [Design Decision DEC-COLOR-01] WCAG AAA 状态徽标 -->
                <Badge :status="session.status" />
              </td>
              <td class="py-3 px-4 text-slate-600 dark:text-slate-300">
                {{ session.current_stage }}
              </td>
              <td class="py-3 px-4 font-mono">v{{ session.version }}</td>
              <td class="py-3 px-4 text-slate-400">{{ session.created_at }}</td>
              <td class="py-3 px-4 text-right space-x-2">
                <router-link :to="`/runs/${session.session_id}`">
                  <Button size="sm" variant="secondary">详情</Button>
                </router-link>
                <!-- 活动任务允许取消 -->
                <Button
                  v-if="session.status === 'running' || session.status === 'created'"
                  size="sm"
                  variant="danger"
                  @click="handleCancel(session.session_id)"
                >
                  取消
                </Button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import Card from '@/components/common/Card.vue'
import Button from '@/components/common/Button.vue'
import Badge from '@/components/common/Badge.vue'
import AppIcon from '@/components/icons/AppIcon.vue'
import { useRunStore } from '@/stores/runStore'

const runStore = useRunStore()
const filterWorkflowId = ref('')

async function fetchList() {
  await runStore.fetchSessions({
    workflow_id: filterWorkflowId.value || undefined,
    limit: 50,
  })
}

async function handleCancel(sessionId: string) {
  if (confirm(`确定要取消正在执行的任务 ${sessionId} 吗？`)) {
    try {
      await runStore.cancelRun(sessionId)
      await fetchList()
    } catch (err: any) {
      alert(`取消失败: ${err.message}`)
    }
  }
}

onMounted(() => {
  fetchList()
})
</script>
