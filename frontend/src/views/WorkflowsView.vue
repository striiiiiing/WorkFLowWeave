<template>
  <div class="space-y-6">
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <div>
        <h2 class="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
          工作流管理 (Workflows)
        </h2>
        <p class="text-sm text-slate-500 dark:text-slate-400 mt-1">
          配置与编排多源采集、并行分析与通知流程
        </p>
      </div>

      <router-link to="/workflows/new">
        <Button icon="plus">创建新工作流</Button>
      </router-link>
    </div>

    <!-- 列表展示 -->
    <div v-if="workflowStore.loading" class="p-12 text-center text-slate-400">
      <AppIcon name="loader" :spin="true" class="mx-auto mb-2" size="lg" />
      <span>加载工作流定义中...</span>
    </div>

    <div v-else-if="workflowStore.workflows.length === 0" class="p-12 text-center border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-xl">
      <AppIcon name="workflow" class="mx-auto mb-3 text-slate-300 dark:text-slate-600" size="xl" />
      <h3 class="text-base font-semibold text-slate-700 dark:text-slate-300">暂无已保存的工作流</h3>
      <p class="text-xs text-slate-400 mt-1 mb-4">点击下方按钮开始通过零代码流式编排器创建第一个工作流</p>
      <router-link to="/workflows/new">
        <Button icon="plus">立即创建</Button>
      </router-link>
    </div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
      <Card
        v-for="wf in workflowStore.workflows"
        :key="wf.id"
        :title="wf.name || wf.id"
        :subtitle="wf.description || '未填写描述'"
        icon="workflow"
        hover
      >
        <template #header-actions>
          <span class="font-mono text-xs text-slate-400">ID: {{ wf.id }}</span>
        </template>

        <div class="space-y-3 text-xs text-slate-600 dark:text-slate-300">
          <div class="flex items-center justify-between">
            <span class="text-slate-400">采集源数量:</span>
            <span class="font-semibold">{{ wf.sources?.length || 0 }} 个</span>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-slate-400">分析任务分支:</span>
            <span class="font-semibold">{{ wf.analysis_tasks?.length || 0 }} 个</span>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-slate-400">汇聚汇总 (fan-in):</span>
            <span :class="wf.fan_in?.enabled ? 'text-green-600 font-semibold' : 'text-slate-400'">
              {{ wf.fan_in?.enabled ? '已开启' : '未启用' }}
            </span>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-slate-400">通知目标:</span>
            <span class="font-semibold">{{ wf.channels?.length || 0 }} 个</span>
          </div>
        </div>

        <template #footer>
          <div class="flex items-center gap-2">
            <!-- [Design Decision DEC-ICON-01] 动作图标与对象图标明确区分 -->
            <Button size="sm" icon="play" @click="triggerRun(wf.id)">
              运行
            </Button>
            <router-link :to="`/workflows/${wf.id}/edit`">
              <Button size="sm" variant="secondary" icon="edit">编辑</Button>
            </router-link>
          </div>

          <Button size="sm" variant="ghost" class="text-red-500 hover:text-red-700" @click="deleteWf(wf.id)">
            删除
          </Button>
        </template>
      </Card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import Card from '@/components/common/Card.vue'
import Button from '@/components/common/Button.vue'
import AppIcon from '@/components/icons/AppIcon.vue'
import { useWorkflowStore } from '@/stores/workflowStore'
import { useRunStore } from '@/stores/runStore'

const router = useRouter()
const workflowStore = useWorkflowStore()
const runStore = useRunStore()

async function triggerRun(id: string) {
  try {
    const sessionId = await runStore.triggerWorkflow(id)
    router.push(`/runs/${sessionId}`)
  } catch (err: any) {
    alert(`触发失败: ${err.message}`)
  }
}

async function deleteWf(id: string) {
  if (confirm(`确定要永久删除工作流 ${id} 吗？`)) {
    await workflowStore.deleteWorkflow(id)
  }
}

onMounted(() => {
  workflowStore.fetchWorkflows()
})
</script>
