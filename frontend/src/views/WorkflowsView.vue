<script setup lang="ts">
import { workflowsApi } from '@/api/workflows'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { runsApi } from '@/api/runs'
import { useQuery } from '@/shared/async/useQuery'
import { useAsyncTask } from '@/shared/async/useAsyncTask'
import PageHeader from '@/shared/ui/PageHeader.vue'
import AppIcon from '@/shared/ui/icons/AppIcon.vue'
import AgentContinueButton from '@/components/agent/AgentContinueButton.vue'
const router = useRouter()
const search = ref('')
const { data, pending, error, refresh } = useQuery((signal) => workflowsApi.list(signal))
const action = useAsyncTask()
const filtered = computed(
  () =>
    data.value?.filter((item) =>
      `${item.id} ${item.name}`.toLowerCase().includes(search.value.toLowerCase()),
    ) ?? [],
)
function trigger(id: string) {
  void action.run(async () => {
    const result = await runsApi.trigger(id)
    await router.push(`/runs/${result.session_id}`)
  })
}
function remove(id: string) {
  void action.run(async () => {
    await workflowsApi.delete(id)
    await refresh()
  })
}
</script>
<template>
  <PageHeader title="工作流管理" description="多源采集、并行分析与通知分发">
    <el-button :loading="pending" @click="refresh">刷新</el-button>
    <router-link to="/workflows/new"><el-button type="primary">新建工作流</el-button></router-link>
  </PageHeader>
  <el-alert
    v-if="error || action.error.value"
    :title="error || action.error.value"
    type="error"
    :closable="false"
    show-icon
  />
  <el-input
    v-model="search"
    placeholder="搜索工作流 ID 或名称"
    aria-label="搜索工作流"
    clearable
    class="mb-6"
  />
  <div v-loading="pending" class="grid grid-cols-1 xl:grid-cols-2 gap-5">
    <el-card v-for="workflow in filtered" :key="workflow.id" shadow="hover">
      <template #header>
        <div class="flex items-center justify-between gap-3">
          <div class="flex items-center gap-3">
            <AppIcon name="workflow" />
            <div>
              <h2 class="font-semibold">{{ workflow.name || workflow.id }}</h2>
              <p class="mono muted text-xs mt-1">{{ workflow.id }}</p>
            </div>
          </div>
          <el-tag :type="workflow.enabled ? 'success' : 'info'">
            {{ workflow.enabled ? '已启用' : '已停用' }}
          </el-tag>
        </div>
      </template>
      <div class="flex flex-wrap gap-3 muted text-sm">
        <span>{{ workflow.sources.length }} 个数据源</span>
        <span>{{ workflow.analyses.length }} 个分析任务</span>
        <span>{{ workflow.channels.length }} 个通知渠道</span>
      </div>
      <div class="flex flex-wrap justify-end gap-2 mt-6">
        <AgentContinueButton :workflow-id="workflow.id" />
        <el-popconfirm title="确认删除此工作流？" @confirm="remove(workflow.id)">
          <template #reference>
            <el-button type="danger" plain :disabled="action.pending.value">删除</el-button>
          </template>
        </el-popconfirm>
        <router-link :to="`/workflows/${workflow.id}/edit`">
          <el-button>编辑</el-button>
        </router-link>
        <el-button
          type="primary"
          :loading="action.pending.value"
          :disabled="!workflow.enabled"
          @click="trigger(workflow.id)"
        >
          立即运行
        </el-button>
      </div>
    </el-card>
  </div>
  <el-empty v-if="!pending && !error && !filtered.length" description="暂无匹配的工作流" />
</template>
