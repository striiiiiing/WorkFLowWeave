<script setup lang="ts">
import { computed, ref } from 'vue'
import type { SchemaCapability } from '@/shared/schema/types'
import type { SourceConfig, SourceSaveTarget, SourceUsageView } from '../model/types'
import type { SourceEditorController } from '../composables/useSourceEditor'
import type { CredentialProtector } from '../model/types'
import SourceConfigEditor from './SourceConfigEditor.vue'
const props = defineProps<{
  editor: SourceEditorController
  target: SourceSaveTarget
  initial: boolean
  capabilities: readonly SchemaCapability[]
  usages?: readonly SourceUsageView[]
  protect: CredentialProtector
}>()
const emit = defineEmits<{ saved: [value: SourceConfig]; cancel: [] }>()
const form = ref<InstanceType<typeof SourceConfigEditor>>()
const scope = computed(() =>
  props.target.kind === 'workflow-draft'
    ? '仅修改当前工作流，保存工作流后生效。'
    : !props.initial
      ? '保存到资源配置中心，可供多个工作流使用。'
      : props.usages === undefined
        ? '工作流使用位置未知；保存会更新共用配置。'
        : `同步到 ${props.usages.filter((item) => !item.detached).length} 个共用工作流。`,
)
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
    <template #header="{ titleId, titleClass }">
      <div class="source-editor-heading">
        <div>
          <h2 :id="titleId" :class="titleClass">
            {{
              !initial
                ? '新增数据源'
                : target.kind === 'workflow-draft'
                  ? '编辑独立配置'
                  : '编辑共用数据源'
            }}
          </h2>
          <p class="muted text-sm mt-1">{{ scope }}</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <el-switch
            v-if="editor.value.value"
            :model-value="editor.value.value.enabled"
            active-text="启用数据源"
            aria-label="启用数据源"
            :disabled="editor.save.pending.value"
            @update:model-value="editor.updateBasic({ enabled: Boolean($event) })"
          />
          <el-button @click="emit('cancel')">取消</el-button>
          <el-button
            type="primary"
            :loading="editor.save.pending.value"
            :disabled="!editor.value.value || !!editor.load.error.value"
            @click="form?.submit()"
          >
            {{ target.kind === 'workflow-draft' ? '应用到当前工作流' : '保存资源' }}
          </el-button>
        </div>
      </div>
    </template>
    <el-alert
      v-if="editor.load.error.value"
      :title="editor.load.error.value"
      type="error"
      :closable="false"
    />
    <el-button v-if="editor.load.error.value" @click="editor.load.refresh">
      重新加载数据源
    </el-button>
    <el-skeleton v-if="editor.load.pending.value" :rows="8" />
    <template v-else-if="editor.value.value && !editor.load.error.value">
      <SourceConfigEditor
        ref="form"
        header-actions
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
<style scoped>
.source-editor-heading {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}
</style>
