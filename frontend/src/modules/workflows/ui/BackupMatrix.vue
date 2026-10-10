<script setup lang="ts">
import type { WorkflowEditorController } from '../composables/useWorkflowEditor'
import { retentionFields } from '../model/create/backup'
import SectionCard from '@/shared/ui/SectionCard.vue'
const props = defineProps<{ editor: WorkflowEditorController }>()
const fields = [
  { key: 'snapshot', label: '配置与静态提示词' },
  { key: 'collection', label: '采集正文' },
  { key: 'analysis', label: '分析结果' },
  { key: 'final', label: '最终正文' },
] as const
const draft = () => props.editor.draft.value!.backup
</script>
<template>
  <SectionCard title="5. 长期正文与保留">
    <template #actions>
      <el-switch
        :model-value="draft().enabled"
        aria-label="启用长期正文备份"
        @update:model-value="editor.updateBackup({ enabled: Boolean($event) })"
      />
    </template>
    <p class="muted text-sm mb-4">正文开关仅控制长期归档；执行 checkpoint 仍可能包含内容，并按独立期限保留。</p>
    <div class="form-grid">
      <el-form-item v-for="field in fields" :key="field.key" :label="field.label">
        <el-switch
          :model-value="draft()[field.key]"
          :disabled="!draft().enabled"
          @update:model-value="editor.updateBackup({ [field.key]: Boolean($event) })"
        />
      </el-form-item>
      <el-form-item v-for="field in retentionFields" :key="field.key" :label="field.label + '（留空不过期）'">
        <el-input-number
          :model-value="draft()[field.key] ?? undefined"
          :min="1"
          :precision="0"
          :disabled="field.key !== 'checkpoint_retention_days' && !draft().enabled"
          @update:model-value="editor.updateBackup({ [field.key]: $event ?? null })"
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
