<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { resourcesApi } from '@/api/resources'
import { useAsyncTask } from '@/composables/useAsyncTask'
import { sourceName, sourceUsage } from '@/domain/resources'
import { sourcePolicies } from '@/domain/forms'
import type { SourceConfig, WorkflowDefinition } from '@/types'
import SectionCard from '@/components/common/SectionCard.vue'
import SourceEditorDrawer from '@/components/resources/SourceEditorDrawer.vue'
import SourceSummary from '@/components/resources/SourceSummary.vue'
import AppIcon from '@/components/icons/AppIcon.vue'

const model = defineModel<WorkflowDefinition>({ required: true })
const props = withDefaults(
  defineProps<{
    sources: SourceConfig[]
    workflows?: WorkflowDefinition[]
    savedWorkflowId?: string
    advanced?: boolean
  }>(),
  { workflows: () => [] },
)
const emit = defineEmits<{ savedSource: [source: SourceConfig] }>()
const action = useAsyncTask()
const loadingSources = ref(false)
const selected = ref<string[]>([])
const editor = ref<{ initial?: SourceConfig; local?: boolean }>()
const currentWorkflows = computed(() => [
  ...props.workflows.filter(
    (workflow) => workflow.id !== (props.savedWorkflowId ?? model.value.id),
  ),
  model.value,
])
function sharedCount(id: string) {
  return sourceUsage(id, currentWorkflows.value).filter((usage) => !usage.detached).length
}
function sourceById(id: string) {
  return (
    model.value.source_overrides[id]?.source ?? props.sources.find((source) => source.id === id)
  )
}
function hasSharedSource(id: string) {
  return props.sources.some((source) => source.id === id)
}
function move(index: number, delta: number) {
  const ids = [...model.value.sources]
  const target = index + delta
  if (target < 0 || target >= ids.length) return
  ;[ids[index], ids[target]] = [ids[target], ids[index]]
  model.value = { ...model.value, sources: ids }
}
function selectSources(ids: string[]) {
  model.value = {
    ...model.value,
    sources: ids,
    source_overrides: Object.fromEntries(
      Object.entries(model.value.source_overrides).filter(([id]) => ids.includes(id)),
    ),
  }
}
function loadSources() {
  selectSources([
    ...model.value.sources,
    ...selected.value.filter((id) => !model.value.sources.includes(id)),
  ])
  loadingSources.value = false
  selected.value = []
}
function detach(id: string) {
  void action.run(async () => {
    const source = await resourcesApi.resolveSource(id, model.value.source_overrides[id])
    model.value = {
      ...model.value,
      source_overrides: {
        ...model.value.source_overrides,
        [id]: { source, options: {}, setters: {}, template: null },
      },
    }
  })
}
function restore(id: string) {
  const overrides = { ...model.value.source_overrides }
  delete overrides[id]
  model.value = { ...model.value, source_overrides: overrides }
}
function publishSource(id: string) {
  const source = model.value.source_overrides[id]?.source
  if (!source) return
  void action.run(async () => {
    const saved = hasSharedSource(id)
      ? await resourcesApi.replace('sources', id, source)
      : await resourcesApi.create('sources', source)
    emit('savedSource', saved)
    restore(id)
    ElMessage.success('共用数据源已保存；保存工作流后恢复同步。')
  })
}
function editSource(id: string) {
  const initial = sourceById(id)
  if (!initial) return
  const override = model.value.source_overrides[id]
  const local = !!override?.source
  if (override && !local) return
  if (!local && sharedCount(id) > 1) return
  editor.value = { initial, local }
}
function savedSource(source: SourceConfig) {
  if (editor.value?.local) {
    model.value = {
      ...model.value,
      source_overrides: {
        ...model.value.source_overrides,
        [source.id]: { source, options: {}, setters: {}, template: null },
      },
    }
  } else {
    emit('savedSource', source)
    if (!model.value.sources.includes(source.id)) selectSources([...model.value.sources, source.id])
  }
  editor.value = undefined
}
</script>

<template>
  <div>
    <SectionCard
      title="1. 数据采集"
      description="按顺序汇集输入，共用设置可同步，独立配置仅用于当前工作流"
    >
      <template #actions>
        <div class="flex flex-wrap gap-2">
          <el-button @click="loadingSources = true">加载已有数据源</el-button>
          <el-button type="primary" @click="editor = {}">新增采集源</el-button>
        </div>
      </template>
      <el-alert
        v-if="action.error.value"
        :title="action.error.value"
        type="error"
        :closable="false"
      />
      <el-form-item
        prop="sources"
        :rules="{ type: 'array', required: true, min: 1, message: '至少选择一个采集源' }"
      >
        <p v-if="!model.sources.length" class="muted">加载已有数据源，或直接新增采集源。</p>
      </el-form-item>
      <article
        v-for="(sourceId, index) in model.sources"
        :key="sourceId"
        class="source-card"
        :aria-label="`数据源 ${sourceId}`"
      >
        <div class="source-card-heading">
          <div class="flex items-center gap-3 min-w-0 flex-wrap">
            <span class="source-index">{{ index + 1 }}</span>
            <AppIcon name="database" />
            <h3 class="font-semibold break-all">
              {{ sourceById(sourceId) ? sourceName(sourceById(sourceId)!) : sourceId }}
            </h3>
            <el-tag
              :type="model.source_overrides[sourceId]?.source ? 'warning' : 'success'"
              effect="plain"
            >
              {{
                model.source_overrides[sourceId]?.source
                  ? '独立配置'
                  : `全局同步 (${sharedCount(sourceId)})`
              }}
            </el-tag>
            <el-tag
              v-if="model.source_overrides[sourceId] && !model.source_overrides[sourceId]?.source"
              type="info"
            >
              含本流调整
            </el-tag>
          </div>
          <div class="flex gap-1">
            <el-button
              :disabled="index === 0"
              :aria-label="`上移 ${sourceId}`"
              @click="move(index, -1)"
            >
              上移
            </el-button>
            <el-button
              :disabled="index === model.sources.length - 1"
              :aria-label="`下移 ${sourceId}`"
              @click="move(index, 1)"
            >
              下移
            </el-button>
          </div>
        </div>
        <template v-if="sourceById(sourceId)">
          <p v-if="sourceById(sourceId)?.description" class="muted text-sm mb-3">
            {{ sourceById(sourceId)?.description }}
          </p>
          <p
            v-if="model.source_overrides[sourceId] && !model.source_overrides[sourceId]?.source"
            class="muted text-xs mb-2"
          >
            以下为共用基础配置；此工作流另有局部调整，先脱离共用配置即可查看并编辑完整生效设置。
          </p>
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
                model.source_overrides[sourceId]?.source
                  ? '独立配置不再接收资源中心的修改；保存工作流后生效。'
                  : sharedCount(sourceId) > 1
                    ? '多个工作流共用此数据源，单独修改请先脱离共用配置。'
                    : '当前工作流是唯一共用位置，可直接保存数据源。'
              }}
            </p>
            <div class="flex flex-wrap gap-2">
              <el-button
                :disabled="
                  !model.source_overrides[sourceId]?.source &&
                  (!!model.source_overrides[sourceId] || sharedCount(sourceId) > 1)
                "
                @click="editSource(sourceId)"
              >
                编辑配置
              </el-button>
              <el-popconfirm
                v-if="model.source_overrides[sourceId] && hasSharedSource(sourceId)"
                title="恢复后放弃当前工作流的独立设置，使用资源中心的最新配置？"
                @confirm="restore(sourceId)"
              >
                <template #reference><el-button>恢复共用配置</el-button></template>
              </el-popconfirm>
              <el-button
                v-if="!model.source_overrides[sourceId]?.source"
                :loading="action.pending.value"
                @click="detach(sourceId)"
              >
                脱离共用配置
              </el-button>
              <el-popconfirm
                v-else
                :title="`将此配置保存到资源中心，并同步到 ${sharedCount(sourceId)} 个共用工作流？`"
                @confirm="publishSource(sourceId)"
              >
                <template #reference>
                  <el-button :loading="action.pending.value">保存为共用数据源</el-button>
                </template>
              </el-popconfirm>
              <el-button
                type="danger"
                plain
                @click="selectSources(model.sources.filter((id) => id !== sourceId))"
              >
                移除
              </el-button>
            </div>
          </div>
        </template>
        <template v-else>
          <el-alert
            title="数据源不存在，请恢复资源或从工作流移除。"
            type="error"
            :closable="false"
          />
          <el-button
            type="danger"
            @click="selectSources(model.sources.filter((id) => id !== sourceId))"
          >
            移除
          </el-button>
        </template>
      </article>
      <div class="form-grid">
        <el-form-item v-if="advanced" label="采集并发数">
          <el-input-number v-model="model.collection_concurrency" :min="1" :precision="0" />
        </el-form-item>
        <el-form-item v-if="advanced" label="全部为空时">
          <el-select v-model="model.on_all_empty">
            <el-option
              v-for="policy in sourcePolicies"
              :key="policy.value"
              :value="policy.value"
              :label="policy.label"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="advanced" label="来源之间的输入分隔符">
          <el-input v-model="model.input_separator" type="textarea" :rows="2" />
          <p class="muted text-sm">
            用于拼接各来源的采集正文，默认空一行（两个换行）；不是采集文件的字段分隔符。
          </p>
        </el-form-item>
        <el-form-item v-if="advanced" label="包含采集数量">
          <el-switch v-model="model.include_counts" />
        </el-form-item>
      </div>
    </SectionCard>
    <el-dialog
      v-model="loadingSources"
      title="加载已有数据源"
      width="min(94vw, 640px)"
      append-to-body
    >
      <p class="muted mb-4">加载后跟随资源配置中心；已有数据源不会重复添加。</p>
      <el-select
        v-model="selected"
        multiple
        filterable
        placeholder="选择数据源"
        aria-label="选择数据源"
      >
        <el-option
          v-for="source in sources"
          :key="source.id"
          :value="source.id"
          :label="sourceName(source) + (source.enabled ? '' : '（已停用）')"
          :disabled="!source.enabled || model.sources.includes(source.id)"
        />
      </el-select>
      <template #footer>
        <el-button @click="loadingSources = false">取消</el-button>
        <el-button type="primary" :disabled="!selected.length" @click="loadSources">
          加入当前工作流
        </el-button>
      </template>
    </el-dialog>
    <SourceEditorDrawer
      v-if="editor"
      :initial="editor.initial"
      :local="editor.local"
      :override="
        editor.local && editor.initial ? model.source_overrides[editor.initial.id] : undefined
      "
      :linked-count="editor.initial ? sharedCount(editor.initial.id) : 0"
      @saved="savedSource"
      @cancel="editor = undefined"
    />
  </div>
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
