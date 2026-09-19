<script setup lang="ts">
import type { BackupPolicy } from '@/types'
import SectionCard from '@/components/common/SectionCard.vue'
const model = defineModel<BackupPolicy>({ required: true })
const fields = [
  { key: 'snapshot', label: '工作流快照' },
  { key: 'collection', label: '采集正文' },
  { key: 'analysis', label: '分析结果' },
  { key: 'final', label: '最终正文' },
] as const
</script>
<template>
  <SectionCard title="5. 持久化与备份">
    <template #actions><el-switch v-model="model.enabled" aria-label="启用备份" /></template>
    <div class="form-grid">
      <el-form-item v-for="field in fields" :key="field.key" :label="field.label">
        <el-switch v-model="model[field.key]" :disabled="!model.enabled" />
      </el-form-item>
      <el-form-item label="保留天数（留空永久保留）">
        <el-input-number
          :model-value="model.retention_days ?? undefined"
          :min="1"
          :precision="0"
          :disabled="!model.enabled"
          @update:model-value="model.retention_days = $event ?? null"
        />
      </el-form-item>
      <el-form-item label="备份失败时">
        <el-select v-model="model.on_failure" :disabled="!model.enabled">
          <el-option value="stop" label="停止" />
          <el-option value="continue" label="继续" />
        </el-select>
      </el-form-item>
    </div>
  </SectionCard>
</template>
