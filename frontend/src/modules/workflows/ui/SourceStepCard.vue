<script setup lang="ts">
import { ref } from 'vue'
import type { SchemaCapability } from '@/shared/schema/types'
import type {
  Credential,
  SourceConfig,
  SourceConfigEditorGateway,
  SourceUsageView,
} from '@/modules/resources/public'
import type { WorkflowDefinition } from '../model/types'
import type { WorkflowEditorController } from '../composables/useWorkflowEditor'
import { SourceEditorSession } from '@/modules/resources/public'
import SectionCard from '@/shared/ui/SectionCard.vue'
import SourceBindingList from './SourceBindingList.vue'
import SourceSelector from './SourceSelector.vue'
const props = withDefaults(
  defineProps<{
    editor: WorkflowEditorController
    sources: readonly SourceConfig[]
    workflows?: readonly WorkflowDefinition[]
    usage?: (id: string) => readonly SourceUsageView[] | undefined
    gateway: SourceConfigEditorGateway
    capabilities: readonly SchemaCapability[]
    protect: (plaintext: string) => Promise<Extract<Credential, { kind: 'encrypted' }>>
    advanced?: boolean
  }>(),
  { workflows: () => [] },
)
const editorOpen = ref<{ id?: string; local: boolean }>()
const loading = ref(false)
const restoreErrors = ref<Record<string, string>>({})
const draft = () => props.editor.draft.value!
function sourceById(id: string) {
  return draft().source_overrides[id]?.source ?? props.sources.find((source) => source.id === id)
}
function hasShared(id: string) {
  return props.sources.some((source) => source.id === id)
}
function select(ids: readonly string[]) {
  props.editor.setSourceIds(ids)
}
function saveSource(value: SourceConfig) {
  const session = editorOpen.value
  if (!session) return
  if (session.local) props.editor.applySource(value.id, value)
  else if (!draft().sources.includes(value.id)) props.editor.addSourceId(value.id)
  editorOpen.value = undefined
}
function openSource(id: string, local: boolean) {
  editorOpen.value = { id, local }
}
function addSelected(ids: readonly string[]) {
  select([...draft().sources, ...ids])
  loading.value = false
}
function detach(id: string) {
  void props.editor.detachSource(id, props.gateway)
}
function restore(id: string) {
  if (!hasShared(id)) {
    restoreErrors.value = {
      ...restoreErrors.value,
      [id]: '来源不存在，无法恢复共用配置；当前独立配置仍保留。',
    }
    return
  }
  const next = { ...restoreErrors.value }
  delete next[id]
  restoreErrors.value = next
  props.editor.restoreSharedSource(id)
}
function publish(id: string) {
  void props.editor.publishSource(id, props.gateway, hasShared(id))
}
</script>
<template>
  <SectionCard
    title="1. 数据采集"
    description="按顺序汇集输入，共用设置可同步，独立配置仅用于当前工作流"
  >
    <template #actions>
      <div class="flex flex-wrap gap-2">
        <el-button @click="loading = true">加载已有数据源</el-button>
        <el-button type="primary" @click="editorOpen = { local: false }">新增采集源</el-button>
      </div>
    </template>
    <el-alert
      v-if="editor.sourceError.value"
      :title="editor.sourceError.value"
      type="error"
      :closable="false"
    />
    <el-form-item
      prop="sources"
      :rules="{ type: 'array', required: true, min: 1, message: '至少选择一个采集源' }"
    >
      <p v-if="!draft().sources.length" class="muted">加载已有数据源，或直接新增采集源。</p>
    </el-form-item>
    <SourceBindingList
      :draft="draft()"
      :sources="sources"
      :usage="usage"
      :pending="editor.sourcePending.value"
      :restore-errors="restoreErrors"
      @move="editor.reorderSource"
      @edit="(sourceId) => openSource(sourceId, !!draft().source_overrides[sourceId]?.source)"
      @detach="detach"
      @restore="restore"
      @publish="publish"
      @remove="(sourceId) => select(draft().sources.filter((id) => id !== sourceId))"
    />
    <div v-if="advanced" class="form-grid">
      <el-form-item label="采集并发数">
        <el-input-number
          :model-value="draft().collection_concurrency"
          :min="1"
          :precision="0"
          @update:model-value="editor.update({ collection_concurrency: $event ?? 1 })"
        />
      </el-form-item>
      <el-form-item label="全部为空时">
        <el-select
          :model-value="draft().on_all_empty"
          @update:model-value="editor.update({ on_all_empty: $event })"
        >
          <el-option value="stop" label="停止" />
          <el-option value="notice" label="提示" />
          <el-option value="skip" label="跳过" />
        </el-select>
      </el-form-item>
      <el-form-item label="来源之间的输入分隔符">
        <el-input
          :model-value="draft().input_separator"
          type="textarea"
          :rows="2"
          @update:model-value="editor.update({ input_separator: $event })"
        />
      </el-form-item>
      <el-form-item label="包含采集数量">
        <el-switch
          :model-value="draft().include_counts"
          @update:model-value="editor.update({ include_counts: Boolean($event) })"
        />
      </el-form-item>
    </div>
    <SourceSelector
      :open="loading"
      :sources="sources"
      :current-ids="draft().sources"
      @update:open="loading = $event"
      @add="addSelected"
    />
    <SourceEditorSession
      v-if="editorOpen"
      :key="`${editorOpen.local ? 'workflow-draft' : 'shared-resource'}:${editorOpen.id || 'new'}`"
      :initial="editorOpen.id ? sourceById(editorOpen.id) : undefined"
      :override="editorOpen.id ? draft().source_overrides[editorOpen.id] : undefined"
      :target="
        editorOpen.local
          ? { kind: 'workflow-draft', workflowId: draft().id, sourceId: editorOpen.id! }
          : { kind: 'shared-resource', resourceId: editorOpen.id || '' }
      "
      :gateway="gateway"
      :capabilities="capabilities"
      :protect="protect"
      :usages="editorOpen.id ? usage?.(editorOpen.id) : undefined"
      @saved="saveSource"
      @cancel="editorOpen = undefined"
    />
  </SectionCard>
</template>
