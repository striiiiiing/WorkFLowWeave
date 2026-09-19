<script setup lang="ts">
import type { SourceConfig, WorkflowDefinition } from '@/types'
import { sourcePolicies } from '@/domain/forms'
import SectionCard from '@/components/common/SectionCard.vue'
const model = defineModel<WorkflowDefinition>({ required: true })
defineProps<{ sources: SourceConfig[] }>()
function selectSources(ids: string[]) {
  model.value = {
    ...model.value,
    sources: ids,
    source_overrides: Object.fromEntries(
      Object.entries(model.value.source_overrides).filter(([id]) => ids.includes(id)),
    ),
  }
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
          :label="source.id"
        />
      </el-select>
    </el-form-item>
    <div class="form-grid">
      <el-form-item label="采集并发">
        <el-input-number v-model="model.collection_concurrency" :min="1" :precision="0" />
      </el-form-item>
      <el-form-item label="全部为空时">
        <el-select v-model="model.on_all_empty">
          <el-option
            v-for="policy in sourcePolicies"
            :key="policy.value"
            :value="policy.value"
            :label="policy.label"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="输入分隔符">
        <el-input v-model="model.input_separator" type="textarea" :rows="2" />
      </el-form-item>
      <el-form-item label="包含采集数量"><el-switch v-model="model.include_counts" /></el-form-item>
    </div>
    <p v-if="!sources.length" class="muted">请先在资源配置中创建数据源。</p>
  </SectionCard>
</template>
