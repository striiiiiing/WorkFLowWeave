<script setup lang="ts">
import { ref } from 'vue'
import type {
  SourceConfig,
  SourceConfigEditorGateway,
  SourceUsageView,
} from '@/modules/resources/public'
import type { WorkflowDefinition } from '../model/public'
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
    advanced?: boolean
    catalogRefreshing?: boolean
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
    <el-form-item prop="sources">
      <p v-if="!draft().sources.length" class="muted">可添加采集源，或直接使用提示词运行任务。</p>
    </el-form-item>
    <SourceBindingList
      :draft="draft()"
      :sources="sources"
      :usage="usage"
      :pending="editor.sourcePending.value"
      :refreshing="catalogRefreshing"
      :restore-errors="restoreErrors"
      @move="editor.reorderSource"
      @edit="(sourceId) => openSource(sourceId, !!draft().source_overrides[sourceId]?.source)"
      @detach="detach"
      @restore="restore"
      @publish="publish"
      @refresh="$emit('refresh')"
      @remove="(sourceId) => select(draft().sources.filter((id) => id !== sourceId))"
    />
    <el-form-item label="输入格式">
      <el-select
        aria-label="输入格式"
        :model-value="draft().input_processing.format"
        @update:model-value="
          editor.update({ input_processing: { ...draft().input_processing, format: $event } })
        "
      >
        <el-option
          v-for="format in ['none', 'ison', 'toon', 'zon', 'md', 'csv']"
          :key="format"
          :value="format"
          :label="format === 'none' ? '原始表示（JSON / 文本）' : format.toUpperCase()"
        />
      </el-select>
    </el-form-item>
    <p class="muted text-sm">JSON 内容可转换为下列格式；默认保留原始表示。格式转换不等同于 LLM 摘要。</p>
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
      <el-form-item
        v-for="limit in [
          ['total_tokens', '总输入 token'],
          ['item_tokens', '单项 token'],
          ['field_tokens', '字段 token'],
        ] as const"
        :key="limit[0]"
        :label="limit[1]"
      >
        <el-input-number
          :model-value="draft().input_processing[limit[0]]"
          :min="1"
          :precision="0"
          @update:model-value="
            editor.update({
              input_processing: { ...draft().input_processing, [limit[0]]: $event || null },
            })
          "
        />
      </el-form-item>
      <p class="muted text-sm">
        仅 JSON 内容进行格式转换；空白限额表示不截取。来源可覆盖单项和字段限额。
      </p>
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
      :usages="editorOpen.id ? usage?.(editorOpen.id) : undefined"
      @saved="saveSource"
      @cancel="editorOpen = undefined"
    />
  </SectionCard>
</template>
