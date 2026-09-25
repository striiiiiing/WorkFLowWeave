<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance } from 'element-plus'
import PageHeader from '@/shared/ui/PageHeader.vue'
import SectionCard from '@/shared/ui/SectionCard.vue'
import AppIcon from '@/shared/ui/icons/AppIcon.vue'
import { useAsyncTask } from '@/shared/async/useAsyncTask'
import { useQuery } from '@/shared/async/useQuery'
import { useCapabilities, useSystemApi } from '@/modules/system/public'
import { useResourcesApi, type SourceConfigEditorGateway } from '@/modules/resources/public'
import { useSourceUsage } from '@/pages/integrations/useSourceUsage'
import {
  useWorkflowEditor,
  useWorkflowList,
  useWorkflowsApi,
  validateWorkflow,
  SourceStepCard,
  FanOutTaskCard,
  FanInCard,
  NotificationCard,
  BackupMatrix,
} from '@/modules/workflows/public'
const route = useRoute()
const router = useRouter()
const id = computed(() => (route.params.id ? String(route.params.id) : undefined))
const workflowsApi = useWorkflowsApi()
const resourcesApi = useResourcesApi()
const systemApi = useSystemApi()
const workflowQuery = useQuery(
  (signal) => (id.value ? workflowsApi.get(id.value, signal) : Promise.resolve(undefined)),
  [id],
)
const workflowList = useWorkflowList(workflowsApi)
const catalog = useQuery(async (signal) => {
  const [sources, channels, configs] = await Promise.all([
    resourcesApi.list('sources', signal),
    resourcesApi.list('channels', signal),
    resourcesApi.list('ai', signal),
  ])
  return { sources, channels, configs }
})
const capabilities = useCapabilities(systemApi)
const editor = useWorkflowEditor({ identity: id, data: workflowQuery.data })
const usage = useSourceUsage({ query: workflowList, currentDraft: () => editor.draft.value })
const save = useAsyncTask()
const form = ref<FormInstance>()
const advanced = ref(false)
const draft = computed(() => editor.draft.value!)
const catalogValue = computed(() => catalog.data.value!)
const activeStage = computed(() =>
  ['sources', 'analyses', 'fanin', 'channels'].includes(String(route.query.stage))
    ? String(route.query.stage)
    : 'all',
)
const gateway: SourceConfigEditorGateway = {
  resolve: resourcesApi.resolveSource,
  async save(target, value) {
    if (target.kind === 'workflow-draft') {
      editor.applySource(target.sourceId, value)
      return
    }
    const exists = catalog.data.value?.sources.some((source) => source.id === target.resourceId)
    if (exists) await resourcesApi.replace('sources', target.resourceId, value)
    else await resourcesApi.create('sources', value)
    await catalog.refresh()
    await workflowList.refresh()
  },
}
function selectStage(stage: string) {
  void router.replace({ query: { ...route.query, stage } })
}
async function submit() {
  const draft = editor.draft.value
  if (!draft) return
  const errors = validateWorkflow(draft)
  if (errors.length) {
    await router.replace({ query: { ...route.query, stage: 'all' } })
    return
  }
  const valid = (await form.value?.validate().catch(() => false)) ?? false
  if (!valid) return
  await save.run(async () => {
    if (id.value) await workflowsApi.replace(id.value, draft)
    else await workflowsApi.create(draft)
    ElMessage.success('工作流已保存')
    await router.push('/workflows')
  })
}
function refreshCatalog() {
  void catalog.refresh()
  void workflowList.refresh()
}
onMounted(() => window.addEventListener('focus', refreshCatalog))
onScopeDispose(() => window.removeEventListener('focus', refreshCatalog))
const stages = computed(
  () =>
    [
      {
        id: 'sources',
        title: '数据采集源',
        detail: `${editor.draft.value?.sources.length ?? 0} 个输入源`,
      },
      {
        id: 'analyses',
        title: '并行 AI 分析',
        detail: `${editor.draft.value?.analyses.length ?? 0} 路任务`,
      },
      {
        id: 'fanin',
        title: '汇聚汇总',
        detail: editor.draft.value?.fan_in ? '已启用汇总' : '未启用',
      },
      {
        id: 'channels',
        title: '渠道分发',
        detail: `${editor.draft.value?.channels.length ?? 0} 个渠道`,
      },
    ] as const,
)
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
          !editor.ready.value ||
          !catalog.data.value ||
          !!catalog.error.value ||
          !!workflowQuery.error.value
        "
        @click="submit"
      >
        保存工作流
      </el-button>
    </PageHeader>
    <el-alert
      v-if="
        workflowQuery.error.value ||
        catalog.error.value ||
        capabilities.error.value ||
        save.error.value
      "
      :title="
        workflowQuery.error.value ||
        catalog.error.value ||
        capabilities.error.value ||
        save.error.value
      "
      type="error"
      :closable="false"
      show-icon
    />
    <el-button v-if="catalog.error.value" @click="catalog.refresh">重新加载资源目录</el-button>
    <el-skeleton v-if="!editor.ready.value || !catalog.data.value" :rows="10" animated />
    <div v-else class="pipeline-main-column">
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
          @click="selectStage('all')"
        >
          <AppIcon name="workflow" size="sm" />
          <span>全览模式</span>
        </button>
      </nav>
      <el-form ref="form" novalidate :model="draft" label-position="top" @submit.prevent="submit">
        <el-form-item label="高级模式"><el-switch v-model="advanced" /></el-form-item>
        <div class="flow-stack">
          <SectionCard title="基本信息与运行策略">
            <div class="form-grid">
              <el-form-item label="工作流 ID">
                <el-input
                  :model-value="draft.id"
                  :disabled="!!id"
                  @update:model-value="editor.update({ id: $event })"
                />
              </el-form-item>
              <el-form-item label="显示名称">
                <el-input
                  :model-value="draft.name"
                  @update:model-value="editor.update({ name: $event })"
                />
              </el-form-item>
              <el-form-item label="启用工作流">
                <el-switch
                  :model-value="draft.enabled"
                  @update:model-value="editor.update({ enabled: Boolean($event) })"
                />
              </el-form-item>
              <el-form-item label="定时间隔 / 秒（留空只手动运行）">
                <el-input-number
                  :model-value="draft.interval_seconds ?? undefined"
                  :min="0.001"
                  @update:model-value="editor.update({ interval_seconds: $event ?? null })"
                />
              </el-form-item>
            </div>
          </SectionCard>
          <SourceStepCard
            v-show="activeStage === 'all' || activeStage === 'sources'"
            :editor="editor"
            :sources="catalogValue.sources"
            :workflows="workflowList.data.value ?? []"
            :usage="usage.references"
            :gateway="gateway"
            :capabilities="
              capabilities.data.value?.filter((item) => item.kind === 'collector') ?? []
            "
            :protect="resourcesApi.protectCredential"
            :advanced="advanced"
          />
          <FanOutTaskCard
            v-show="activeStage === 'all' || activeStage === 'analyses'"
            :editor="editor"
            :configs="catalogValue.configs"
            :advanced="advanced"
          />
          <FanInCard
            v-show="activeStage === 'all' || activeStage === 'fanin'"
            :editor="editor"
            :configs="catalogValue.configs"
            :advanced="advanced"
          />
          <NotificationCard
            v-show="activeStage === 'all' || activeStage === 'channels'"
            :editor="editor"
            :channels="catalogValue.channels"
            :capabilities="capabilities.data.value?.filter((item) => item.kind === 'channel') ?? []"
            :advanced="advanced"
          />
          <BackupMatrix v-if="advanced" :editor="editor" />
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
