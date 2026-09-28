<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance } from 'element-plus'
import PageHeader from '@/shared/ui/PageHeader.vue'
import { useAsyncTask } from '@/shared/async/useAsyncTask'
import { useQuery } from '@/shared/async/useQuery'
import { useCapabilities, useSystemApi } from '@/modules/system/public'
import {
  ChannelEditor,
  useResourcesApi,
  type ChannelConfig,
  type SourceConfigEditorGateway,
} from '@/modules/resources/public'
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
  hasLegacyRetention,
  WorkflowBasicInfo,
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
watch(() => editor.draft.value?.backup, (backup) => {
  if (backup && hasLegacyRetention(backup)) advanced.value = true
}, { immediate: true })
const channelEditor = ref<{ initial?: ChannelConfig }>()
const draft = computed(() => editor.draft.value!)
const catalogValue = computed(() => catalog.data.value!)
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
async function submit() {
  const draft = editor.draft.value
  if (!draft) return
  const errors = validateWorkflow(draft)
  if (errors.length) {
    ElMessage.error(errors.join('；'))
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
    <el-skeleton v-if="!editor.ready.value || !catalog.data.value" :rows="10" />
    <div v-else class="pipeline-main-column">
      <el-form ref="form" novalidate :model="draft" label-position="top" @submit.prevent="submit">
        <div class="flow-stack">
          <WorkflowBasicInfo
            :draft="draft"
            :editing="!!id"
            :advanced="advanced"
            @update="editor.update"
            @update:advanced="advanced = $event"
          />
          <SourceStepCard
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
          <FanOutTaskCard :editor="editor" :configs="catalogValue.configs" :advanced="advanced" />
          <FanInCard :editor="editor" :configs="catalogValue.configs" :advanced="advanced" />
          <NotificationCard
            :editor="editor"
            :channels="catalogValue.channels"
            :capabilities="capabilities.data.value?.filter((item) => item.kind === 'channel') ?? []"
            :advanced="advanced"
            @add="channelEditor = {}"
            @edit="channelEditor = { initial: $event }"
          />
          <BackupMatrix v-if="advanced" :editor="editor" />
        </div>
      </el-form>
    </div>
    <el-dialog
      :model-value="!!channelEditor"
      :title="channelEditor?.initial ? '编辑通知渠道' : '添加通知渠道'"
      width="680px"
      destroy-on-close
      @close="channelEditor = undefined"
    >
      <ChannelEditor
        v-if="channelEditor"
        :initial="channelEditor.initial"
        :capabilities="capabilities.data.value?.filter((item) => item.kind === 'channel') ?? []"
        @saved="
          async (value) => {
            channelEditor = undefined
            await catalog.refresh()
            if (!editor.draft.value?.channels.includes(value.id))
              editor.setChannels([...(editor.draft.value?.channels ?? []), value.id])
          }
        "
        @cancel="channelEditor = undefined"
      />
    </el-dialog>
  </div>
</template>
<style scoped>
.pipeline-main-column {
  min-width: 0;
}
</style>
