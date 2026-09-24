<script setup lang="ts">
import { workflowsApi } from '@/api/workflows'
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { resourcesApi } from '@/api/resources'
import {
  resourceKinds,
  resourceNames,
  sourceName,
  sourceUsage,
  type EditableKind,
  type EditableResource,
} from '@/domain/resources'
import type { SourceConfig } from '@/types'
import { useQuery } from '@/shared/async/useQuery'
import { useAsyncTask } from '@/shared/async/useAsyncTask'
import PageHeader from '@/shared/ui/PageHeader.vue'
import AppIcon from '@/shared/ui/icons/AppIcon.vue'
import ResourceEditor from '@/components/resources/ResourceEditor.vue'
import SourceEditorDrawer from '@/components/resources/SourceEditorDrawer.vue'
import SourceSummary from '@/components/resources/SourceSummary.vue'
const route = useRoute()
const router = useRouter()
const kind = computed<EditableKind>({
  get: () => resourceKinds.find((item) => item.key === route.query.kind)?.key ?? 'sources',
  set: (value) => {
    void router.replace({ query: { ...route.query, kind: value } })
  },
})
const { data, pending, error, refresh } = useQuery(
  (signal) => resourcesApi.list(kind.value, signal),
  [kind],
)
const {
  data: workflows,
  pending: workflowsPending,
  error: workflowsError,
  refresh: refreshWorkflows,
} = useQuery(
  (signal) =>
    kind.value === 'sources' ? workflowsApi.list(signal) : Promise.resolve([]),
  [kind],
)
const action = useAsyncTask()
const editor = ref<{ kind: EditableKind; initial?: EditableResource }>()
const dialog = ref(false)
const sourceEditor = ref<{ initial?: SourceConfig; linkedCount: number }>()
const sourceSearch = ref('')
const sourceFilter = ref<'all' | 'shared' | 'independent' | 'unused'>('all')
const sources = computed(
  () => data.value?.filter((item): item is SourceConfig => 'collector' in item) ?? [],
)
const filteredSources = computed(() => {
  const query = sourceSearch.value.trim().toLocaleLowerCase()
  return sources.value.filter((source) => {
    const usage = workflows.value ? sourceUsage(source.id, workflows.value) : []
    const matchesQuery =
      !query ||
      [sourceName(source), source.id, source.description ?? '', source.collector]
        .join(' ')
        .toLocaleLowerCase()
        .includes(query)
    if (!matchesQuery) return false
    if (sourceFilter.value === 'all') return true
    if (!workflows.value) return false
    if (sourceFilter.value === 'unused') return usage.length === 0
    if (sourceFilter.value === 'shared') return usage.some((item) => !item.detached)
    return usage.some((item) => item.detached)
  })
})
function sourceReferences(sourceId: string) {
  return workflows.value ? sourceUsage(sourceId, workflows.value) : undefined
}
function linkedCount(sourceId: string): number | undefined {
  return sourceReferences(sourceId)?.filter((item) => !item.detached).length
}
function open(initial?: EditableResource) {
  if (kind.value === 'sources') {
    const source = initial as SourceConfig | undefined
    if (source && !workflows.value) {
      ElMessage.warning('工作流使用位置尚不可用，加载成功后才能编辑此数据源')
      return
    }
    sourceEditor.value = {
      initial: source,
      linkedCount: source ? (linkedCount(source.id) ?? 0) : 0,
    }
    return
  }
  editor.value = { kind: kind.value, initial }
  dialog.value = true
}
function remove(id: string) {
  const target = kind.value
  void action.run(async () => {
    await resourcesApi.delete(target, id)
    await refresh()
  })
}
function saved(value?: EditableResource) {
  if (editor.value?.kind === 'ai' && value) editor.value.initial = value
  else dialog.value = false
  void refresh()
}
function savedSource() {
  sourceEditor.value = undefined
  void refresh()
  void refreshWorkflows()
}
function updateSourceEnabled(source: SourceConfig, enabled: boolean | string | number) {
  void action.run(async () => {
    await resourcesApi.replace('sources', source.id, { ...source, enabled: Boolean(enabled) })
    await refresh()
  })
}
function refreshCurrentData() {
  void refresh()
  if (kind.value === 'sources') void refreshWorkflows()
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
      :loading="pending || (kind === 'sources' && workflowsPending)"
      @click="refreshCurrentData"
    >
      刷新
    </el-button>
    <el-button type="primary" @click="open()">添加{{ resourceNames[kind] }}</el-button>
  </PageHeader>
  <el-alert
    v-if="error || action.error.value"
    :title="error || action.error.value"
    type="error"
    :closable="false"
    show-icon
  />
  <el-card shadow="never">
    <el-tabs v-model="kind">
      <el-tab-pane
        v-for="category in resourceKinds"
        :key="category.key"
        :name="category.key"
        :label="category.label"
      />
    </el-tabs>
    <p v-if="kind === 'ai'" class="muted text-sm mb-4">
      在渠道中配置连接并添加模型，保存后供工作流选择；健康检查位于渠道编辑窗口内。
    </p>
    <template v-if="kind === 'sources'">
      <div class="flex flex-wrap items-center gap-3 mb-4">
        <el-input
          v-model="sourceSearch"
          clearable
          placeholder="搜索名称、编号、说明或采集器"
          aria-label="搜索数据源"
          class="max-w-md"
        />
        <el-radio-group
          v-model="sourceFilter"
          aria-label="按工作流使用情况筛选"
          class="flex max-w-full flex-wrap"
        >
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="shared">共用引用</el-radio-button>
          <el-radio-button value="independent">独立引用</el-radio-button>
          <el-radio-button value="unused">未使用</el-radio-button>
        </el-radio-group>
      </div>
      <el-alert
        v-if="workflowsError"
        :title="`工作流使用位置读取失败：${workflowsError}。引用数量和筛选结果暂不可用。`"
        type="error"
        :closable="false"
        show-icon
      >
        <template #default>
          <el-button size="small" @click="refreshWorkflows">重新加载工作流使用位置</el-button>
        </template>
      </el-alert>
      <el-skeleton v-if="pending" :rows="4" animated />
      <div v-else class="grid grid-cols-1 gap-4">
        <el-card v-for="source in filteredSources" :key="source.id" shadow="never">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="flex items-start gap-3 min-w-0">
              <AppIcon name="database" />
              <div class="min-w-0">
                <h2 class="font-semibold break-all">{{ sourceName(source) }}</h2>
                <p class="mono muted text-xs mt-1">{{ source.id }}</p>
                <p v-if="source.description" class="muted text-sm mt-2">
                  {{ source.description }}
                </p>
              </div>
            </div>
            <el-switch
              :model-value="source.enabled"
              :disabled="action.pending.value"
              :aria-label="`${sourceName(source)} 启用状态`"
              active-text="已启用"
              inactive-text="已停用"
              @change="updateSourceEnabled(source, $event)"
            />
          </div>
          <SourceSummary :source="source" class="mt-4" />
          <div class="mt-4 border-t pt-3">
            <div class="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
              <strong>使用位置</strong>
              <template v-if="workflowsError">
                <span class="muted">引用关系暂不可用</span>
              </template>
              <template v-else-if="workflowsPending || !workflows">
                <span class="muted">正在读取工作流使用位置…</span>
              </template>
              <template v-else>
                <span class="muted">
                  同步到 {{ linkedCount(source.id) }} 个工作流，{{
                    sourceReferences(source.id)?.filter((item) => item.detached).length
                  }}
                  个独立引用
                </span>
                <router-link
                  v-for="usage in sourceReferences(source.id)"
                  :key="usage.id"
                  :to="`/workflows/${usage.id}/edit`"
                  class="inline-flex"
                >
                  <el-tag :type="usage.detached ? 'warning' : 'success'" effect="plain">
                    {{ usage.name }}{{ usage.detached ? ' · 独立' : ' · 共用' }}
                  </el-tag>
                </router-link>
                <span v-if="!sourceReferences(source.id)?.length" class="muted">
                  暂无工作流使用
                </span>
              </template>
            </div>
          </div>
          <div class="flex justify-end gap-2 mt-4">
            <el-button :disabled="!workflows || workflowsPending" @click="open(source)">
              编辑
            </el-button>
            <el-popconfirm title="确认删除此数据源？" @confirm="remove(source.id)">
              <template #reference>
                <el-button type="danger" plain :disabled="action.pending.value">删除</el-button>
              </template>
            </el-popconfirm>
          </div>
        </el-card>
      </div>
      <el-empty
        v-if="!pending && !error && !filteredSources.length"
        :description="
          workflowsError && sourceFilter !== 'all'
            ? '工作流目录不可用，无法筛选引用状态'
            : '此分类暂无匹配的数据源'
        "
      />
      <SourceEditorDrawer
        v-if="sourceEditor"
        :initial="sourceEditor.initial"
        :linked-count="sourceEditor.linkedCount"
        @saved="savedSource"
        @cancel="sourceEditor = undefined"
      />
    </template>
    <template v-else>
      <div v-loading="pending" class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <el-card v-for="resource in data" :key="resource.id" shadow="never">
          <div class="flex items-start gap-3">
            <AppIcon :name="resourceKinds.find((item) => item.key === kind)!.icon" />
            <div class="min-w-0">
              <h2 class="font-semibold mono break-all">{{ resource.id }}</h2>
              <p class="muted text-sm mt-2">
                {{
                  'collector' in resource
                    ? resource.collector
                    : 'provider' in resource
                      ? resource.base_url || '尚未配置服务地址'
                      : resource.channel
                }}
              </p>
              <p v-if="'models' in resource" class="muted text-sm mt-2">
                {{ Object.keys(resource.models).length }} 个已配置模型
              </p>
            </div>
          </div>
          <div class="flex justify-end gap-2 mt-5">
            <el-button @click="open(resource)">编辑</el-button>
            <el-popconfirm title="确认删除此资源？" @confirm="remove(resource.id)">
              <template #reference>
                <el-button type="danger" plain :disabled="action.pending.value">删除</el-button>
              </template>
            </el-popconfirm>
          </div>
        </el-card>
      </div>
      <el-empty v-if="!pending && !error && !data?.length" description="此分类暂无资源" />
    </template>
  </el-card>
  <el-dialog
    v-model="dialog"
    :title="(editor?.initial ? '编辑' : '添加') + resourceNames[editor?.kind ?? kind]"
    width="680px"
    destroy-on-close
  >
    <ResourceEditor
      v-if="editor && dialog"
      :kind="editor.kind"
      :initial="editor.initial"
      @saved="saved"
      @cancel="dialog = false"
    />
  </el-dialog>
</template>
