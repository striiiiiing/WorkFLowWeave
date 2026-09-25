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
import { SourceEditorSession, SourceSummary } from '@/modules/resources/public'
import SectionCard from '@/shared/ui/SectionCard.vue'
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
const selected = ref<string[]>([])
const loading = ref(false)
const draft = () => props.editor.draft.value!
function sourceById(id: string) {
  return draft().source_overrides[id]?.source ?? props.sources.find((source) => source.id === id)
}
function sharedCount(id: string) {
  return (props.usage?.(id) ?? []).filter((item) => !item.detached).length
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
function addSelected() {
  select([...draft().sources, ...selected.value])
  loading.value = false
  selected.value = []
}
function detach(id: string) {
  void props.editor.detachSource(id, props.gateway)
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
    <article v-for="(sourceId, index) in draft().sources" :key="sourceId" class="source-card">
      <div class="source-card-heading">
        <div class="flex items-center gap-3 min-w-0 flex-wrap">
          <span class="source-index">{{ index + 1 }}</span>
          <h3 class="font-semibold break-all">
            {{ sourceById(sourceId)?.display_name || sourceId }}
          </h3>
          <el-tag
            :type="draft().source_overrides[sourceId]?.source ? 'warning' : 'success'"
            effect="plain"
          >
            {{
              draft().source_overrides[sourceId]?.source
                ? '独立配置'
                : `全局同步 (${sharedCount(sourceId)})`
            }}
          </el-tag>
        </div>
        <div class="flex gap-1">
          <el-button :disabled="index === 0" @click="editor.reorderSource(index, -1)">
            上移
          </el-button>
          <el-button
            :disabled="index === draft().sources.length - 1"
            @click="editor.reorderSource(index, 1)"
          >
            下移
          </el-button>
        </div>
      </div>
      <template v-if="sourceById(sourceId)">
        <SourceSummary :source="sourceById(sourceId)!" />
        <el-alert
          v-if="sourceById(sourceId)?.enabled === false"
          title="此数据源已停用，本次运行不会采集；重新启用后会恢复原设置。"
          type="warning"
          :closable="false"
          class="mt-3"
        />
        <div class="source-card-footer">
          <p class="muted text-xs">
            {{
              draft().source_overrides[sourceId]?.source
                ? '独立配置不再接收资源中心的修改；保存工作流后生效。'
                : sharedCount(sourceId) > 1
                  ? '多个工作流共用此数据源，单独修改请先脱离共用配置。'
                  : '当前工作流是唯一共用位置，可直接保存数据源。'
            }}
          </p>
          <div class="flex flex-wrap gap-2">
            <el-button
              :disabled="
                !draft().source_overrides[sourceId]?.source &&
                (!!draft().source_overrides[sourceId] || sharedCount(sourceId) > 1)
              "
              @click="openSource(sourceId, !!draft().source_overrides[sourceId]?.source)"
            >
              编辑配置
            </el-button>
            <el-button
              v-if="draft().source_overrides[sourceId]"
              @click="props.editor.restoreSharedSource(sourceId)"
            >
              恢复共用配置
            </el-button>
            <el-button
              v-if="!draft().source_overrides[sourceId]?.source"
              :loading="editor.sourcePending.value"
              @click="detach(sourceId)"
            >
              脱离共用配置
            </el-button>
            <el-button v-else :loading="editor.sourcePending.value" @click="publish(sourceId)">
              保存为共用数据源
            </el-button>
            <el-button
              type="danger"
              plain
              @click="select(draft().sources.filter((id) => id !== sourceId))"
            >
              移除
            </el-button>
          </div>
        </div>
      </template>
      <el-alert
        v-else
        title="数据源不存在，请恢复资源或从工作流移除。"
        type="error"
        :closable="false"
      />
      <el-button
        v-if="!sourceById(sourceId)"
        type="danger"
        @click="select(draft().sources.filter((id) => id !== sourceId))"
      >
        移除
      </el-button>
    </article>
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
    <el-dialog v-model="loading" title="加载已有数据源" width="min(94vw, 640px)" append-to-body>
      <el-select v-model="selected" multiple filterable>
        <el-option
          v-for="source in sources"
          :key="source.id"
          :value="source.id"
          :label="source.display_name || source.id"
          :disabled="!source.enabled || draft().sources.includes(source.id)"
        />
      </el-select>
      <template #footer>
        <el-button @click="loading = false">取消</el-button>
        <el-button type="primary" :disabled="!selected.length" @click="addSelected">
          加入当前工作流
        </el-button>
      </template>
    </el-dialog>
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
<style scoped>
.source-card {
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 16px;
}
.source-card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
}
.source-index {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border-radius: 6px;
  padding: 3px 9px;
  font-weight: 700;
}
.source-card-footer {
  border-top: 1px solid var(--el-border-color-lighter);
  margin-top: 16px;
  padding-top: 14px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
</style>
