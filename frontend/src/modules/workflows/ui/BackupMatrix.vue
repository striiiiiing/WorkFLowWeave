<script setup lang="ts">
import type { WorkflowEditorController } from '../composables/useWorkflowEditor'
import SectionCard from '@/shared/ui/SectionCard.vue'
const props = defineProps<{ editor: WorkflowEditorController }>()
const fields = [
  { key: 'snapshot', label: '工作流快照' },
  { key: 'collection', label: '采集正文' },
  { key: 'analysis', label: '分析结果' },
  { key: 'final', label: '最终正文' },
] as const
const draft = () => props.editor.draft.value!.backup
</script>
<template>
  <SectionCard title="5. 持久化与备份">
    <template #actions>
      <el-switch
        :model-value="draft().enabled"
        aria-label="启用备份"
        @update:model-value="editor.updateBackup({ enabled: Boolean($event) })"
      />
    </template>
    <div class="form-grid">
      <el-form-item v-for="field in fields" :key="field.key" :label="field.label">
        <el-switch
          :model-value="draft()[field.key]"
          :disabled="!draft().enabled"
          @update:model-value="editor.updateBackup({ [field.key]: Boolean($event) })"
        />
      </el-form-item>
      <el-form-item label="保留天数（留空永久保留）">
        <el-input-number
          :model-value="draft().retention_days ?? undefined"
          :min="1"
          :precision="0"
          :disabled="!draft().enabled"
          @update:model-value="editor.updateBackup({ retention_days: $event ?? null })"
        />
      </el-form-item>
      <el-form-item label="备份失败时">
        <el-select
          :model-value="draft().on_failure"
          :disabled="!draft().enabled"
          @update:model-value="editor.updateBackup({ on_failure: $event })"
        >
          <el-option value="stop" label="停止" />
          <el-option value="continue" label="继续" />
        </el-select>
      </el-form-item>
    </div>
  </SectionCard>
</template>
