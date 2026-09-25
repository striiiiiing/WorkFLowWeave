<script setup lang="ts">
import type { WorkflowChanges } from '../model/actions'
import type { WorkflowDefinition } from '../model/types'
import SectionCard from '@/shared/ui/SectionCard.vue'

defineProps<{
  draft: WorkflowDefinition
  editing: boolean
}>()
const emit = defineEmits<{ update: [changes: WorkflowChanges] }>()
</script>

<template>
  <SectionCard title="基本信息与运行策略">
    <div class="form-grid">
      <el-form-item label="工作流 ID">
        <el-input
          :model-value="draft.id"
          :disabled="editing"
          @update:model-value="emit('update', { id: $event })"
        />
      </el-form-item>
      <el-form-item label="显示名称">
        <el-input
          :model-value="draft.name"
          @update:model-value="emit('update', { name: $event })"
        />
      </el-form-item>
      <el-form-item label="启用工作流">
        <el-switch
          :model-value="draft.enabled"
          @update:model-value="emit('update', { enabled: Boolean($event) })"
        />
      </el-form-item>
      <el-form-item label="定时间隔 / 秒（留空只手动运行）">
        <el-input-number
          :model-value="draft.interval_seconds ?? undefined"
          :min="0.001"
          @update:model-value="emit('update', { interval_seconds: $event ?? null })"
        />
      </el-form-item>
    </div>
  </SectionCard>
</template>
