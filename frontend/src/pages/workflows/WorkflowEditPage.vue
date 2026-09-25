<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance } from 'element-plus'
import PageHeader from '@/shared/ui/PageHeader.vue'
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
  WorkflowBasicInfo,
  WorkflowStageNav,
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
const resourceSavePending = ref(false)
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
    const hadDetachedOverride = !!editor.draft.value?.source_overrides[target.resourceId]?.source
    if (exists) await resourcesApi.replace('sources', target.resourceId, value)
    else await resourcesApi.create('sources', value)
    await catalog.refresh()
    await workflowList.refresh()
    if (hadDetachedOverride) resourceSavePending.value = true
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
  const result = await save.run(async () => {
    if (id.value) await workflowsApi.replace(id.value, draft)
    else await workflowsApi.create(draft)
    ElMessage.success('工作流已保存')
    await router.push('/workflows')
  })
  if (result.status === 'success') resourceSavePending.value = false
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
      v-if="resourceSavePending"
      title="资源已保存，工作流仍待保存"
      type="warning"
      :closable="false"
      show-icon
    />
    <el-alert
      v-else-if="editor.dirty.value"
      title="工作流有未保存更改"
      type="warning"
      :closable="false"
      show-icon
    />
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
      <WorkflowStageNav :active-stage="activeStage" :stages="stages" @select="selectStage" />
      <el-form ref="form" novalidate :model="draft" label-position="top" @submit.prevent="submit">
        <el-form-item label="高级模式"><el-switch v-model="advanced" /></el-form-item>
        <div class="flow-stack">
          <WorkflowBasicInfo :draft="draft" :editing="!!id" @update="editor.update" />
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
</style>
