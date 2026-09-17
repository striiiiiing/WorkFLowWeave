<template>
  <div class="max-w-4xl mx-auto space-y-6 pb-12">
    <!-- 头部导航与保存操作栏 -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 sticky top-0 z-20 bg-slate-50/90 dark:bg-slate-900/90 backdrop-blur py-3 border-b border-slate-200 dark:border-slate-800">
      <div>
        <h2 class="text-xl font-bold tracking-tight text-slate-900 dark:text-slate-100 flex items-center gap-2">
          <router-link to="/workflows" class="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200">
            工作流
          </router-link>
          <span class="text-slate-300">/</span>
          <span>{{ isNew ? '新建工作流' : `编辑：${workflow.name || workflow.id}` }}</span>
        </h2>
        <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
          采用无画布流式阶梯编排器，按序编排采集、多分支分析、汇聚及通知
        </p>
      </div>

      <div class="flex items-center gap-3">
        <router-link to="/workflows">
          <Button variant="ghost">取消</Button>
        </router-link>
        <Button :loading="saving" @click="handleSave">
          保存工作流
        </Button>
      </div>
    </div>

    <!-- [Design Decision DEC-LAYOUT-01] 基础信息配置卡片 -->
    <Card title="基本信息与标识符" subtitle="工作流唯一 ID 与展示名称">
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Input
          v-model="workflow.id"
          label="工作流 ID (ASCII 标识符)"
          placeholder="如：nightly_log_analysis"
          :disabled="!isNew"
          required
          mono
          :error="errors.id"
          hint="保存后不可更改，只能包含字母、数字、下划线及短横线"
        />
        <Input
          v-model="workflow.name"
          label="工作流显示名称"
          placeholder="如：夜间系统日志分析与汇总"
          required
          :error="errors.name"
        />
        <div class="sm:col-span-2">
          <Input
            v-model="workflow.description"
            label="详细描述"
            as="textarea"
            :rows="2"
            placeholder="说明该工作流的业务目标与触发场景..."
          />
        </div>
      </div>
    </Card>

    <!-- 流程图指示器：阶段 1 -->
    <div class="flex justify-center">
      <div class="w-0.5 h-6 bg-blue-300 dark:bg-blue-700" />
    </div>

    <!-- 阶段 1：数据采集与共享输入编排 -->
    <SourceStepCard
      :workflow="workflow"
      :available-sources="resourceStore.sources"
    />

    <!-- 流程图指示器：阶段 2 -->
    <div class="flex justify-center">
      <div class="w-0.5 h-6 bg-blue-300 dark:bg-blue-700" />
    </div>

    <!-- 阶段 2：Fan-Out 并行分析任务 -->
    <FanOutTaskCard
      :workflow="workflow"
      :available-a-is="resourceStore.ais"
    />

    <!-- 流程图指示器：阶段 3 -->
    <div class="flex justify-center">
      <div class="w-0.5 h-6 bg-blue-300 dark:bg-blue-700" />
    </div>

    <!-- 阶段 3：Fan-In 汇聚汇总 -->
    <FanInCard
      :workflow="workflow"
      :available-a-is="resourceStore.ais"
    />

    <!-- 流程图指示器：阶段 4 -->
    <div class="flex justify-center">
      <div class="w-0.5 h-6 bg-blue-300 dark:bg-blue-700" />
    </div>

    <!-- 阶段 4：通知渠道分发 -->
    <NotificationCard
      :workflow="workflow"
      :available-channels="resourceStore.channels"
    />

    <!-- 流程图指示器：阶段 5 -->
    <div class="flex justify-center">
      <div class="w-0.5 h-6 bg-blue-300 dark:bg-blue-700" />
    </div>

    <!-- 阶段 5：持久化与备份策略 -->
    <BackupMatrix :policy="workflow.backup_policy" />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Card from '@/components/common/Card.vue'
import Button from '@/components/common/Button.vue'
import Input from '@/components/common/Input.vue'
import SourceStepCard from '@/components/workflow/SourceStepCard.vue'
import FanOutTaskCard from '@/components/workflow/FanOutTaskCard.vue'
import FanInCard from '@/components/workflow/FanInCard.vue'
import NotificationCard from '@/components/workflow/NotificationCard.vue'
import BackupMatrix from '@/components/workflow/BackupMatrix.vue'
import { useWorkflowStore } from '@/stores/workflowStore'
import { useResourceStore } from '@/stores/resourceStore'
import type { WorkflowDefinition } from '@/types'

const route = useRoute()
const router = useRouter()
const workflowStore = useWorkflowStore()
const resourceStore = useResourceStore()

const isNew = computed(() => route.params.id === 'new' || !route.params.id)
const saving = ref(false)
const errors = reactive<Record<string, string>>({})

const workflow = reactive<WorkflowDefinition>({
  id: '',
  name: '',
  description: '',
  sources: [],
  on_error: 'stop',
  on_all_empty: 'skip',
  analysis_tasks: [],
  analysis_failure: 'continue',
  send_partial: false,
  fan_in: {
    enabled: false,
    ai: null,
    model: null,
    prompt: '',
  },
  channels: [],
  backup_policy: {
    enabled: true,
    snapshot: true,
    collection: true,
    analysis: true,
    final: true,
    retention_days: null,
    on_failure: 'stop',
  },
})

async function handleSave() {
  errors.id = ''
  errors.name = ''

  if (!workflow.id) {
    errors.id = '工作流 ID 不能为空'
    return
  }
  if (!workflow.name) {
    errors.name = '工作流名称不能为空'
    return
  }
  if (workflow.sources.length === 0) {
    alert('请至少选择一个采集源以生成共享输入')
    return
  }
  if (workflow.analysis_tasks.length === 0) {
    alert('请至少添加一个并行分析任务 (Fan-out)')
    return
  }

  saving.value = true
  try {
    await workflowStore.saveWorkflow(workflow)
    router.push('/workflows')
  } catch (err: any) {
    alert(`保存失败: ${err.message}`)
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await resourceStore.fetchAllResources()
  if (!isNew.value) {
    const id = String(route.params.id)
    try {
      const existing = await workflowStore.getWorkflow(id)
      Object.assign(workflow, existing)
    } catch {
      alert(`无法加载工作流 ${id}`)
      router.push('/workflows')
    }
  }
})
</script>
