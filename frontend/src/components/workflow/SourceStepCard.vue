<script setup lang="ts">
import type { SourceConfig, WorkflowDefinition } from '@/types'
import { optionSchema, partialSchema } from '@/domain/capabilities'
import { sourcePolicies } from '@/domain/forms'
import { computed } from 'vue'
import { systemApi } from '@/api/system'
import { useQuery } from '@/composables/useQuery'
import ParameterField from '@/components/common/ParameterField.vue'
import SectionCard from '@/components/common/SectionCard.vue'
import SetterTemplateManager from '@/components/resources/SetterTemplateManager.vue'
const model = defineModel<WorkflowDefinition>({ required: true })
const props = defineProps<{ sources: SourceConfig[]; advanced?: boolean }>()
const {
  data: plugins,
  error: pluginError,
  refresh,
} = useQuery((signal) => systemApi.plugins(signal))
const sourceCapabilities = computed(() =>
  Object.fromEntries(
    props.sources.map((source) => [
      source.id,
      plugins.value?.find((item) => item.kind === 'collector' && item.name === source.collector),
    ]),
  ),
)
function move(index: number, delta: number) {
  const ids = [...model.value.sources]
  const target = index + delta
  if (target < 0 || target >= ids.length) return
  ;[ids[index], ids[target]] = [ids[target], ids[index]]
  model.value = { ...model.value, sources: ids }
}
function toggleOverride(id: string, enabled: boolean) {
  const overrides = { ...model.value.source_overrides }
  if (enabled) overrides[id] = { options: {}, setters: {}, template: null }
  else delete overrides[id]
  model.value = { ...model.value, source_overrides: overrides }
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
function sourceById(id: string) {
  return props.sources.find((source) => source.id === id)
}
</script>
<template>
  <SectionCard title="1. 数据采集" description="多个来源按所选顺序合并为共享输入">
    <el-form-item
      label="采集源"
      prop="sources"
      :rules="{ type: 'array', required: true, min: 1, message: '至少选择一个采集源' }"
    >
      <el-select
        :model-value="model.sources"
        multiple
        filterable
        placeholder="选择数据源"
        @update:model-value="selectSources"
      >
        <el-option
          v-for="source in sources"
          :key="source.id"
          :value="source.id"
          :label="`${source.id}${source.enabled ? '' : '（已停用）'}`"
          :disabled="!source.enabled && !model.sources.includes(source.id)"
        />
      </el-select>
    </el-form-item>
    <el-alert v-if="pluginError" :title="pluginError" type="error" :closable="false" />
    <el-button v-if="pluginError" @click="refresh">重新加载采集器选项</el-button>
    <div
      v-for="(sourceId, index) in model.sources"
      :key="sourceId"
      class="border rounded-lg p-4 mb-4"
    >
      <div class="flex flex-wrap items-center gap-2 mb-3">
        <span class="mono break-all">
          {{ index + 1 }}. {{ sourceId
          }}{{ sourceById(sourceId)?.enabled === false ? '（已停用）' : '' }}
        </span>
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
      <el-alert
        v-if="sourceById(sourceId)?.enabled === false"
        title="此数据源已停用，本次运行不会采集；重新启用后会恢复原设置。"
        type="warning"
        :closable="false"
        class="mb-3"
      />
      <el-form-item :label="`${sourceId}：自定义本次采集`">
        <el-switch
          :model-value="!!model.source_overrides[sourceId]"
          @update:model-value="toggleOverride(sourceId, Boolean($event))"
        />
      </el-form-item>
      <template v-if="model.source_overrides[sourceId]">
        <p class="muted text-sm mb-3">
          仅覆盖本工作流；未填写的字段沿用数据源。来源内部排序由下方处理规则决定。
        </p>
        <ParameterField
          v-model="model.source_overrides[sourceId].options"
          :prop="`source_overrides.${sourceId}.options`"
          label="本次采集参数"
          :schema="optionSchema(sourceCapabilities[sourceId]?.options_schema, 'workflow')"
        />
        <SetterTemplateManager
          :collector="sourceById(sourceId)?.collector ?? ''"
          v-model="model.source_overrides[sourceId].template"
          :schema="sourceCapabilities[sourceId]?.setters_schema"
        />
        <ParameterField
          v-model="model.source_overrides[sourceId].setters"
          :prop="`source_overrides.${sourceId}.setters`"
          label="本次处理规则（含采集器支持的排序）"
          :schema="partialSchema(sourceCapabilities[sourceId]?.setters_schema)"
        />
      </template>
    </div>
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
    <p v-if="!sources.length" class="muted">请先在资源配置中创建数据源。</p>
  </SectionCard>
</template>
