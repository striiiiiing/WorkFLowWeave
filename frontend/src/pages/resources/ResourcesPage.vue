<script setup lang="ts">
import { computed, ref, shallowRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useCapabilities } from '@/modules/system/public'
import { useSourceUsage } from '../integrations/useSourceUsage'
import {
  useResourceList,
  resourceKinds,
  resourceNames,
  ResourceCategoryNavigation,
  SourceFilters,
  SourceList,
  ProviderList,
  ChannelList,
  ChannelEditor,
  AIProviderEditor,
  SourceEditorSession,
  type EditableKind,
  type AIConfig,
  type ChannelConfig,
  type SourceConfig,
  type SourceFilter,
  type SourceConfigEditorGateway,
} from '@/modules/resources/public'
import PageHeader from '@/shared/ui/PageHeader.vue'
const route = useRoute()
const router = useRouter()
const kind = computed<EditableKind>({
  get: () => resourceKinds.find((item) => item.key === route.query.kind)?.key ?? 'sources',
  set: (value) => {
    void router.replace({ query: { ...route.query, kind: value } })
  },
})
const list = useResourceList(kind)
const usage = useSourceUsage()
const capabilities = useCapabilities()
const collectors = computed(
  () => capabilities.data.value?.filter((item) => item.kind === 'collector') ?? [],
)
const channels = computed(
  () => capabilities.data.value?.filter((item) => item.kind === 'channel') ?? [],
)
const sourceSearch = ref('')
const sourceFilter = ref<SourceFilter>('all')
const sourceEditor = shallowRef<{
  initial?: SourceConfig
  gateway: SourceConfigEditorGateway
  sessionId: number
}>()
const providerEditor = shallowRef<{ initial?: AIConfig }>()
const channelEditor = shallowRef<{ initial?: ChannelConfig }>()
let sourceEditorSequence = 0
function openSource(initial?: SourceConfig) {
  sourceEditor.value = {
    initial,
    gateway: list.sourceGateway(!!initial),
    sessionId: ++sourceEditorSequence,
  }
}
function open() {
  if (kind.value === 'sources') openSource()
  else if (kind.value === 'ai') providerEditor.value = {}
  else channelEditor.value = {}
}
function refresh() {
  void list.refresh()
  void capabilities.refresh()
  void usage.refresh()
}
function savedSource() {
  sourceEditor.value = undefined
  void list.refresh()
  void usage.refresh()
}
function openWorkflow(id: string) {
  void router.push({ name: 'workflow-edit', params: { id } })
}
</script>
<template>
  <PageHeader
    :title="kind === 'sources' ? '资源配置中心 · 数据源' : '资源配置中心'"
    :description="
      kind === 'sources' ? '集中管理数据源及其工作流使用位置' : '管理供应商渠道及其模型与通知渠道'
    "
  >
    <el-button
      :loading="list.pending.value || usage.pending.value || capabilities.pending.value"
      @click="refresh"
    >
      刷新
    </el-button>
    <el-button type="primary" @click="open">添加{{ resourceNames[kind] }}</el-button>
  </PageHeader>
  <el-alert
    v-if="list.error.value || list.action.error.value"
    :title="list.error.value || list.action.error.value"
    type="error"
    :closable="false"
    show-icon
  />
  <el-alert
    v-if="capabilities.error.value"
    :title="capabilities.error.value"
    type="error"
    :closable="false"
  >
    <template #default>
      <el-button @click="capabilities.refresh">重新加载插件选项</el-button>
    </template>
  </el-alert>
  <el-card shadow="never">
    <ResourceCategoryNavigation :value="kind" @change="kind = $event" />
    <template v-if="kind === 'sources'">
      <SourceFilters
        :search="sourceSearch"
        :filter="sourceFilter"
        @search="sourceSearch = $event"
        @filter="sourceFilter = $event"
      />
      <SourceList
        :sources="list.sources.value ?? []"
        :search="sourceSearch"
        :filter="sourceFilter"
        :references="usage.references"
        :pending="list.pending.value"
        :error="list.error.value"
        :busy="list.action.pending.value"
        :usage-pending="usage.pending.value"
        :usage-error="usage.error.value"
        @edit="openSource"
        @remove="list.remove"
        @enabled="list.setEnabled"
        @workflow="openWorkflow"
        @retry-usage="usage.refresh"
      />
    </template>
    <template v-else-if="kind === 'ai'">
      <p class="muted text-sm mb-4">
        在渠道中配置连接并添加模型，保存后供工作流选择；健康检查位于渠道编辑窗口内。
      </p>
      <ProviderList
        :resources="list.providers.value ?? []"
        :pending="list.pending.value"
        :error="list.error.value"
        :busy="list.action.pending.value"
        @edit="providerEditor = { initial: $event }"
        @remove="list.remove"
      />
    </template>
    <ChannelList
      v-else
      :resources="list.channels.value ?? []"
      :pending="list.pending.value"
      :error="list.error.value"
      :busy="list.action.pending.value"
      @edit="channelEditor = { initial: $event }"
      @remove="list.remove"
    />
  </el-card>
  <SourceEditorSession
    v-if="sourceEditor"
    :key="sourceEditor.sessionId"
    :initial="sourceEditor.initial"
    :target="{ kind: 'shared-resource', resourceId: sourceEditor.initial?.id ?? '' }"
    :gateway="sourceEditor.gateway"
    :capabilities="collectors"
    :usages="sourceEditor.initial ? usage.references(sourceEditor.initial.id) : []"
    :protect="list.protect"
    @saved="savedSource"
    @cancel="sourceEditor = undefined"
  />
  <el-dialog
    :model-value="!!providerEditor"
    :title="(providerEditor?.initial ? '编辑' : '添加') + '供应商渠道'"
    width="680px"
    destroy-on-close
    @close="providerEditor = undefined"
  >
    <AIProviderEditor
      v-if="providerEditor"
      :initial="providerEditor.initial"
      @saved="
        (value) => {
          providerEditor = { initial: value }
          void list.refresh()
        }
      "
      @cancel="providerEditor = undefined"
    />
  </el-dialog>
  <el-dialog
    :model-value="!!channelEditor"
    :title="(channelEditor?.initial ? '编辑' : '添加') + '通知渠道'"
    width="680px"
    destroy-on-close
    @close="channelEditor = undefined"
  >
    <ChannelEditor
      v-if="channelEditor"
      :initial="channelEditor.initial"
      :capabilities="channels"
      @saved="
        () => {
          channelEditor = undefined
          void list.refresh()
        }
      "
      @cancel="channelEditor = undefined"
    />
  </el-dialog>
</template>
