<script setup lang="ts">
import { computed, ref, shallowRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuery } from '@/shared/async/useQuery'
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
  type MCPServerConfig,
  type MCPHealthReport,
  type SourceFilter,
  type SourceConfigEditorGateway,
  MCPServerEditor,
  useResourcesApi,
} from '@/modules/resources/public'
import { useErrorFormatter } from '@/shared/async/errorFormatter'
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
const resourcesApi = useResourcesApi()
const mcpStatus = useQuery(
  (signal) => (kind.value === 'mcp_servers' ? resourcesApi.mcpStatus(signal) : Promise.resolve([])),
  [() => kind.value === 'mcp_servers'],
)
const formatError = useErrorFormatter()
const usage = useSourceUsage()
const capabilities = useCapabilities()
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
const mcpEditor = shallowRef<{ initial?: MCPServerConfig }>()
const mcpProbeReports = ref<Record<string, MCPHealthReport>>({})
const mcpProbePending = ref<Record<string, boolean>>({})
const mcpProbeError = ref('')
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
  else if (kind.value === 'mcp_servers') mcpEditor.value = {}
  else if (kind.value === 'ai') providerEditor.value = {}
  else channelEditor.value = {}
}
function refresh() {
  void list.refresh()
  if (kind.value === 'mcp_servers') void mcpStatus.refresh()
  void capabilities.refresh()
  void usage.refresh()
}
function savedSource() {
  sourceEditor.value = undefined
  void list.refresh()
  void usage.refresh()
}
function savedMcpServer() {
  mcpEditor.value = undefined
  mcpProbeReports.value = {}
  void list.refresh()
  void mcpStatus.refresh()
}
async function removeMcpServer(id: string) {
  await list.remove(id)
  const reports = { ...mcpProbeReports.value }
  delete reports[id]
  mcpProbeReports.value = reports
}
function mcpHealth(server: MCPServerConfig): MCPHealthReport {
  return (
    mcpProbeReports.value[server.id] ??
    mcpStatus.data.value?.find((item) => item.server === server.id)?.health ?? {
      server: server.id,
      status: 'unknown',
      checked_at: null,
      latency_ms: null,
      tool_count: null,
      error: null,
    }
  )
}
function mcpHealthLabel(status: MCPHealthReport['status']): string {
  return {
    unknown: '未探测',
    healthy: '健康',
    unhealthy: '异常',
    disabled: '已停用',
  }[status]
}
async function probeMcpServer(server: MCPServerConfig) {
  mcpProbeError.value = ''
  mcpProbePending.value = { ...mcpProbePending.value, [server.id]: true }
  try {
    const report = await resourcesApi.probeMcpServer(server.id)
    mcpProbeReports.value = { ...mcpProbeReports.value, [server.id]: report }
    await mcpStatus.refresh()
  } catch (cause) {
    mcpProbeError.value = formatError(cause)
  } finally {
    mcpProbePending.value = { ...mcpProbePending.value, [server.id]: false }
  }
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
  <el-alert
    v-if="kind === 'mcp_servers' && (mcpStatus.error.value || mcpProbeError)"
    :title="mcpStatus.error.value || mcpProbeError"
    type="error"
    :closable="false"
    show-icon
  />
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
    <template v-else-if="kind === 'mcp_servers'">
      <div
        v-for="server in (list.data.value as MCPServerConfig[] | undefined) ?? []"
        :key="server.id"
        class="flex items-center justify-between border-b py-3 gap-3"
      >
        <div>
          <strong>{{ server.id }}</strong>
          <p class="muted text-sm">
            {{ server.transport }} · {{ server.enabled ? '已启用' : '已停用' }}
          </p>
          <p class="muted text-sm">
            健康：{{ mcpHealthLabel(mcpHealth(server).status) }}
            <template v-if="mcpHealth(server).latency_ms !== null">
              · {{ Math.round(mcpHealth(server).latency_ms ?? 0) }} ms
            </template>
            <template v-if="server.health_check_enabled">
              · 自动探测 {{ server.health_check_interval_minutes }} 分钟
            </template>
          </p>
        </div>
        <div class="flex gap-2">
          <el-button :loading="mcpProbePending[server.id]" @click="probeMcpServer(server)">
            探测健康
          </el-button>
          <el-button @click="mcpEditor = { initial: server }">编辑</el-button>
          <el-popconfirm title="删除此 MCP 服务？" @confirm="removeMcpServer(server.id)">
            <template #reference><el-button type="danger" plain>删除</el-button></template>
          </el-popconfirm>
        </div>
      </div>
      <el-empty
        v-if="!list.pending.value && !list.data.value?.length"
        description="暂无 MCP 服务"
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
    :usages="sourceEditor.initial ? usage.references(sourceEditor.initial.id) : []"
    @saved="savedSource"
    @cancel="sourceEditor = undefined"
  />
  <el-dialog
    :model-value="!!mcpEditor"
    :title="mcpEditor?.initial ? '编辑 MCP 服务' : '添加 MCP 服务'"
    width="680px"
    destroy-on-close
    @close="mcpEditor = undefined"
  >
    <MCPServerEditor
      v-if="mcpEditor"
      :initial="mcpEditor.initial"
      @saved="savedMcpServer"
      @cancel="mcpEditor = undefined"
    />
  </el-dialog>
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
      @persisted="() => void list.refresh()"
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
