<script setup lang="ts">
import type { BackupPolicy } from '@/types'
import { classifyLegacyRetention, hasLegacyRetention, retentionFields } from '@/modules/workflows/model/backup'
import SectionCard from '@/shared/ui/SectionCard.vue'
const model = defineModel<BackupPolicy>({ required: true })
const fields = [
  { key: 'snapshot', label: '配置与静态提示词' },
  { key: 'collection', label: '采集正文' },
  { key: 'analysis', label: '分析结果' },
  { key: 'final', label: '最终正文' },
] as const
</script>
<template>
  <SectionCard title="5. 长期正文与保留">
    <template #actions><el-switch v-model="model.enabled" aria-label="启用长期正文备份" /></template>
    <p class="muted text-sm mb-4">正文开关仅控制长期归档；执行 checkpoint 仍可能包含内容，并按独立期限保留。</p>
    <el-alert
      v-if="hasLegacyRetention(model)"
      type="warning"
      :closable="false"
      class="mb-4"
      title="旧版统一保留天数不能自动套用到各类内容。请检查下方四类期限，并确认采用当前设置。"
    />
    <div class="form-grid">
      <el-form-item v-for="field in fields" :key="field.key" :label="field.label">
        <el-switch v-model="model[field.key]" :disabled="!model.enabled" />
      </el-form-item>
      <el-form-item v-for="field in retentionFields" :key="field.key" :label="field.label + '（留空不过期）'">
        <el-input-number
          :model-value="model[field.key] ?? undefined"
          :min="1"
          :precision="0"
          :disabled="field.key !== 'checkpoint_retention_days' && !model.enabled"
          @update:model-value="model[field.key] = $event ?? null"
        />
      </el-form-item>
      <el-form-item label="备份失败时">
        <el-select v-model="model.on_failure" :disabled="!model.enabled">
          <el-option value="stop" label="停止" />
          <el-option value="continue" label="继续" />
        </el-select>
      </el-form-item>
    </div>
    <el-button v-if="hasLegacyRetention(model)" class="mt-4" type="primary" plain @click="model = classifyLegacyRetention(model)">
      确认分类保留设置
    </el-button>
  </SectionCard>
</template>
