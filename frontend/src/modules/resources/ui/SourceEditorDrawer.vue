<script setup lang="ts">
import type { SchemaCapability } from '@/shared/schema/types'
import type { SourceConfig, SourceSaveTarget, SourceUsageView } from '../model/types'
import type { SourceEditorController } from '../composables/useSourceEditor'
import type { CredentialProtector } from '../model/types'
import SourceConfigEditor from './SourceConfigEditor.vue'
defineProps<{
  editor: SourceEditorController
  target: SourceSaveTarget
  initial: boolean
  capabilities: readonly SchemaCapability[]
  usages?: readonly SourceUsageView[]
  protect: CredentialProtector
}>()
const emit = defineEmits<{ saved: [value: SourceConfig]; cancel: [] }>()
</script>
<template>
  <el-drawer
    :model-value="true"
    :title="
      !initial ? '新增数据源' : target.kind === 'workflow-draft' ? '编辑独立配置' : '编辑共用数据源'
    "
    size="min(94vw, 760px)"
    append-to-body
    destroy-on-close
    @close="emit('cancel')"
  >
    <el-alert
      v-if="editor.load.error.value"
      :title="editor.load.error.value"
      type="error"
      :closable="false"
    />
    <el-button v-if="editor.load.error.value" @click="editor.load.refresh">
      重新加载数据源
    </el-button>
    <el-skeleton v-if="editor.load.pending.value" :rows="8" animated />
    <template v-else-if="editor.value.value && !editor.load.error.value">
      <el-alert
        class="mb-5"
        :title="
          target.kind === 'workflow-draft'
            ? '仅修改当前工作流的独立配置，保存工作流后生效。'
            : !initial
              ? '保存后加入资源配置中心，可在多个工作流中使用。'
              : usages === undefined
                ? '工作流使用位置未知；保存会更新共用配置。'
                : `保存后同步到 ${usages.filter((item) => !item.detached).length} 个使用共用配置的工作流，已脱离的工作流不受影响。`
        "
        type="info"
        :closable="false"
        show-icon
      />
      <SourceConfigEditor
        :editor="editor"
        :target="target"
        :initial="initial"
        :capabilities="capabilities"
        :protect="protect"
        @saved="emit('saved', $event)"
        @cancel="emit('cancel')"
      />
    </template>
  </el-drawer>
</template>
