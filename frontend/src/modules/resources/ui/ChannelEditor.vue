<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { ElMessage, type FormInstance } from 'element-plus'
import type { JsonObject } from '@/shared/types'
import type { ChannelConfig } from '../model/types'
import type { SchemaCapability } from '@/shared/schema/types'
import { useChannelEditor } from '../composables/useChannelEditor'
import { idRule } from '../model/forms'
import ParameterField from '@/shared/schema/ParameterField.vue'
import CredentialEditor from './CredentialEditor.vue'
const props = defineProps<{ initial?: ChannelConfig; capabilities: readonly SchemaCapability[] }>()
const emit = defineEmits<{ saved: [value: ChannelConfig]; cancel: [] }>()
const {
  draft,
  updateChannel,
  updateEnabled,
  updateAgentEnabled,
  updateOptions,
  updateAdvanced,
  save,
  capabilities,
  capabilityName,
  capability,
  optionParameterSchema,
  credentialNames,
  credentialValue,
  updateCredential,
  updateId,
  submit: saveDraft,
  protect,
} = useChannelEditor(props)
const form = ref<FormInstance>()
const credentialEditors = new Map<string, InstanceType<typeof CredentialEditor>>()
function setCredentialEditor(name: string, editor: unknown) {
  if (editor && typeof editor === 'object' && 'prepare' in editor) {
    credentialEditors.set(name, editor as InstanceType<typeof CredentialEditor>)
  } else {
    credentialEditors.delete(name)
  }
}
function fieldLabel(schema: JsonObject | undefined, name: string): string {
  const properties = (schema?.properties ?? {}) as Record<string, JsonObject>
  const description = properties[name]?.description
  return typeof description === 'string' && description.trim() ? description : name
}

async function submit() {
  const result = await saveDraft(async () => {
    for (const name of credentialNames.value) {
      const editor = credentialEditors.get(name)
      if (editor) updateCredential(name, await editor.prepare())
    }
    await nextTick()
    return (await form.value?.validate(() => {})) ?? false
  })
  if (result.status === 'success') {
    ElMessage.success('资源已保存')
    emit('saved', result.value)
  }
}
</script>
<template>
  <el-alert
    v-if="save.error.value"
    :title="save.error.value"
    type="error"
    :closable="false"
    show-icon
  />
  <el-form
    ref="form"
    novalidate
    :model="draft"
    :disabled="save.pending.value"
    label-position="top"
    @submit.prevent.stop="submit"
  >
    <el-form-item label="资源编号" prop="id" :rules="{ ...idRule, required: false }">
      <el-input
        :model-value="draft.id"
        :disabled="!!initial"
        placeholder="可自行填写；留空则自动生成"
        @update:model-value="updateId"
      />
    </el-form-item>
    <p v-if="capability" class="muted mb-4">{{ capability.description }}</p>
    <el-alert
      v-if="capabilityName && !capability"
      title="当前插件未注册，请检查插件加载状态或选择已注册能力。"
      type="error"
      :closable="false"
    />
    <el-form-item label="渠道能力名称" prop="channel" :rules="idRule">
      <el-select
        :model-value="draft.channel"
        @update:model-value="updateChannel"
        filterable
        placeholder="选择渠道"
      >
        <el-option
          v-for="item in capabilities"
          :key="item.name"
          :value="item.name"
          :label="item.name"
        />
        <el-option
          v-if="draft.channel && !capability"
          :value="draft.channel"
          :label="draft.channel + '（未注册）'"
          disabled
        />
      </el-select>
    </el-form-item>
    <el-form-item label="启用渠道">
      <el-switch
        :model-value="draft.enabled"
        @update:model-value="updateEnabled(Boolean($event))"
      />
    </el-form-item>
    <el-form-item v-if="capability?.capabilities.includes('conversation')" label="接入 Agent 对话">
      <el-switch
        :model-value="draft.agent_enabled"
        @update:model-value="updateAgentEnabled(Boolean($event))"
      />
    </el-form-item>
    <ParameterField
      v-if="capabilityName"
      :key="`options-${capabilityName}`"
      :model-value="draft.options"
      @update:model-value="updateOptions"
      :excluded-properties="credentialNames"
      prop="options"
      label="插件参数 (options)"
      :schema="optionParameterSchema"
    />
    <CredentialEditor
      v-for="name in credentialNames"
      :key="`${capabilityName}-${name}`"
      :ref="(editor) => setCredentialEditor(name, editor)"
      :model-value="credentialValue(name)"
      :label="fieldLabel(capability?.options_schema, name)"
      :protect="protect"
      @update:model-value="updateCredential(name, $event)"
    />
    <details class="advanced-fields">
      <summary class="report-disclosure">高级配置</summary>
      <el-form-item label="超时 / 秒">
        <el-input-number
          :model-value="draft.timeout"
          @update:model-value="updateAdvanced({ timeout: $event })"
          :min="0.001"
        />
      </el-form-item>
    </details>
    <div class="flex justify-end gap-3">
      <el-button @click="emit('cancel')">取消</el-button>
      <el-button type="primary" native-type="submit" :loading="save.pending.value">
        保存资源
      </el-button>
    </div>
  </el-form>
</template>
