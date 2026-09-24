<script setup lang="ts">
import { workflowsApi } from '@/api/workflows'
import { computed, onMounted, onScopeDispose, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance } from 'element-plus'
import { resourcesApi } from '@/api/resources'
import { createWorkflow } from '@/domain/workflow'
import { idRule } from '@/domain/forms'
import { useQuery } from '@/shared/async/useQuery'
import { useAsyncTask } from '@/shared/async/useAsyncTask'
import PageHeader from '@/shared/ui/PageHeader.vue'
import SectionCard from '@/shared/ui/SectionCard.vue'
import SourceStepCard from '@/components/workflow/SourceStepCard.vue'
import FanOutTaskCard from '@/components/workflow/FanOutTaskCard.vue'
import FanInCard from '@/components/workflow/FanInCard.vue'
import NotificationCard from '@/components/workflow/NotificationCard.vue'
import BackupMatrix from '@/components/workflow/BackupMatrix.vue'
import AppIcon from '@/shared/ui/icons/AppIcon.vue'
const route = useRoute()
const router = useRouter()
const id = computed(() => (route.params.id ? String(route.params.id) : undefined))
const workflow = ref(createWorkflow())
const form = ref<FormInstance>()
const save = useAsyncTask()
const advanced = ref(false)
const {
  data: configs,
  pending: modelsPending,
  error: modelsError,
  refresh: refreshModels,
} = useQuery((signal) => resourcesApi.list('ai', signal))
// Returning from provider configuration updates the catalog without replacing the workflow draft.
onMounted(() => window.addEventListener('focus', refreshModels))
onScopeDispose(() => window.removeEventListener('focus', refreshModels))
const {
  data: catalog,
  pending: catalogPending,
  error: catalogError,
  refresh: refreshCatalog,
} = useQuery(async (signal) => {
  const [sources, channels, workflows] = await Promise.all([
    resourcesApi.list('sources', signal),
    resourcesApi.list('channels', signal),
    workflowsApi.list(signal),
  ])
  return { sources, channels, workflows }
})
const { data, pending, error, refresh } = useQuery(
  (signal) => (id.value ? workflowsApi.get(id.value, signal) : Promise.resolve(createWorkflow())),
  [id],
)
watch(data, (value) => {
  if (value) workflow.value = structuredClone(value)
})
const stages = computed(
  () =>
    [
      {
        id: 'sources',
        title: '数据采集源',
        detail: `${workflow.value.sources.length} 个输入源`,
      },
      {
        id: 'analyses',
        title: '并行 AI 分析',
        detail: `${workflow.value.analyses.length} 路任务`,
      },
      {
        id: 'fanin',
        title: '汇聚汇总',
        detail: workflow.value.fan_in ? '已启用汇总' : '未启用',
      },
      {
        id: 'channels',
        title: '渠道分发',
        detail: `${workflow.value.channels.length} 个渠道`,
      },
    ] as const,
)
const activeStage = computed(() =>
  stages.value.some((stage) => stage.id === route.query?.stage) ? route.query.stage : 'all',
)
function selectStage(stage: string) {
  void router.replace({ query: { ...route.query, stage } })
}
function savedSource() {
  void refreshCatalog()
}
// Returning from the resource center refreshes references without replacing unsaved edits.
onMounted(() => window.addEventListener('focus', refreshCatalog))
onScopeDispose(() => window.removeEventListener('focus', refreshCatalog))
function submit() {
  if (!form.value) return
  const editorForm = form.value
  void save.run(async () => {
    if (!(await editorForm.validate(() => {}))) {
      await router.replace({ query: { ...route.query, stage: 'all' } })
      return
    }
    if (!workflow.value.id) workflow.value.id = crypto.randomUUID()
    if (id.value) await workflowsApi.replace(id.value, workflow.value)
    else await workflowsApi.create(workflow.value)
    ElMessage.success('工作流已保存')
    await router.push('/workflows')
  })
}
</script>
<template>
  <div class="workflow-designer pb-10">
    <PageHeader
      :title="id ? '编辑工作流' : '新建工作流'"
      description="按步骤配置采集、分析、汇聚与分发"
    >
      <router-link to="/workflows"><el-button>取消</el-button></router-link>
      <el-button
        type="primary"
        :loading="save.pending.value"
        :disabled="
          !data ||
          !catalog ||
          !configs ||
          modelsPending ||
          catalogPending ||
          !!modelsError ||
          !!catalogError
        "
        @click="submit"
      >
        保存工作流
      </el-button>
    </PageHeader>
    <el-alert
      v-if="error || catalogError || modelsError || save.error.value"
      :title="error || catalogError || modelsError || save.error.value"
      type="error"
      :closable="false"
      show-icon
    />
    <el-button v-if="error" @click="refresh">重新加载</el-button>
    <el-button v-if="catalogError" @click="refreshCatalog">重新加载资源目录</el-button>
    <el-button v-if="modelsError" @click="refreshModels">重新加载模型列表</el-button>
    <el-skeleton
      v-if="pending || (!catalog && catalogPending) || (!configs && modelsPending)"
      :rows="10"
      animated
    />
    <div v-if="data && configs && catalog" class="pipeline-main-column">
      <nav class="pipeline-step-nav" aria-label="工作流阶段">
        <button
          v-for="(stage, index) in stages"
          :key="stage.id"
          type="button"
          class="step-nav-btn"
          :class="{ active: activeStage === stage.id }"
          :aria-pressed="activeStage === stage.id"
          @click="selectStage(stage.id)"
        >
          <span class="step-num">{{ index + 1 }}</span>
          <span class="step-text">
            <strong>{{ stage.title }}</strong>
            <small>{{ stage.detail }}</small>
          </span>
        </button>
        <button
          type="button"
          class="step-nav-btn overview-btn"
          :class="{ active: activeStage === 'all' }"
          :aria-pressed="activeStage === 'all'"
          @click="selectStage('all')"
        >
          <AppIcon name="workflow" size="sm" />
          <span>全览模式</span>
        </button>
      </nav>
      <el-form
        novalidate
        ref="form"
        :model="workflow"
        label-position="top"
        @submit.prevent="submit"
      >
        <el-form-item label="高级模式"><el-switch v-model="advanced" /></el-form-item>
        <div class="flow-stack">
          <SectionCard title="基本信息与运行策略">
            <div class="form-grid">
              <el-form-item
                label="工作流 ID（留空自动生成）"
                prop="id"
                :rules="{ ...idRule, required: false }"
              >
                <el-input v-model="workflow.id" :disabled="!!id" placeholder="nightly_analysis" />
              </el-form-item>
              <el-form-item label="显示名称">
                <el-input v-model="workflow.name" placeholder="夜间日志分析" />
              </el-form-item>
              <el-form-item label="启用工作流">
                <el-switch v-model="workflow.enabled" />
              </el-form-item>
              <el-form-item label="定时间隔 / 秒（留空只手动运行）">
                <el-input-number
                  :model-value="workflow.interval_seconds ?? undefined"
                  :min="0.001"
                  @update:model-value="workflow.interval_seconds = $event ?? null"
                />
              </el-form-item>
            </div>
          </SectionCard>
          <SourceStepCard
            v-show="activeStage === 'all' || activeStage === 'sources'"
            v-model="workflow"
            :sources="catalog.sources"
            :workflows="catalog.workflows"
            :saved-workflow-id="id"
            :advanced="advanced"
            @saved-source="savedSource"
          />
          <FanOutTaskCard
            v-show="activeStage === 'all' || activeStage === 'analyses'"
            v-model="workflow"
            :configs="configs"
            :advanced="advanced"
          />
          <FanInCard
            v-show="activeStage === 'all' || activeStage === 'fanin'"
            v-model="workflow"
            :configs="configs"
            :advanced="advanced"
          />
          <NotificationCard
            v-show="activeStage === 'all' || activeStage === 'channels'"
            v-model="workflow"
            :channels="catalog.channels"
            :advanced="advanced"
          />
          <BackupMatrix v-if="advanced" v-model="workflow.backup" />
        </div>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.pipeline-main-column {
  min-width: 0;
}
.pipeline-step-nav {
  display: flex;
  flex-wrap: wrap;
  padding: 12px;
  gap: 8px;
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  background: var(--el-bg-color);
  margin-bottom: 20px;
}
.step-nav-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  padding: 12px;
  border-radius: 8px;
  min-height: 48px;
  text-align: left;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}
.step-nav-btn.active {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}
.step-nav-btn:hover {
  background: var(--el-fill-color-light);
}
.step-num {
  display: grid;
  place-items: center;
  border: 1px solid currentColor;
  border-radius: 50%;
  width: 24px;
  height: 24px;
  font-size: 12px;
}
.step-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
}
.step-text small {
  font-size: 11px;
}
.overview-btn {
  justify-content: center;
  flex: 0 1 auto;
  font-size: 12px;
}
@media (max-width: 640px) {
  .step-nav-btn {
    flex-basis: 40%;
    padding: 8px;
  }
  .overview-btn {
    flex-basis: 100%;
  }
}
</style>
