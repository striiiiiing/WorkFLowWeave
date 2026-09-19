<script setup lang="ts">
import { computed, ref, toRaw } from 'vue'
import { ElMessage, type FormInstance } from 'element-plus'
import { resourcesApi } from '@/api/resources'
import { useAsyncTask } from '@/composables/useAsyncTask'
import { createResource, type EditableKind, type EditableResource } from '@/domain/resources'
import { idRule, sourcePolicies } from '@/domain/forms'
import JsonField from '@/components/common/JsonField.vue'
const props = defineProps<{ kind: EditableKind; initial?: EditableResource }>()
const emit = defineEmits<{ saved: []; cancel: [] }>()
const draft = ref(
  props.initial ? structuredClone(toRaw(props.initial)) : createResource(props.kind),
)
const form = ref<FormInstance>()
const save = useAsyncTask()
const credentialMode = ref<'keep' | 'env' | 'none'>('keep')
const environmentName = ref(
  'api_key' in draft.value && draft.value.api_key?.kind === 'env' ? draft.value.api_key.name : '',
)
const models = computed({
  get: () => ('models' in draft.value ? draft.value.models : {}),
  set: (value) => {
    if ('models' in draft.value)
      draft.value.models = value as Record<string, import('@/types').JsonObject>
  },
})
const policyFields = [
  { key: 'on_error', label: '采集失败' },
  { key: 'on_missing', label: '来源缺失' },
  { key: 'on_empty', label: '采集为空' },
  { key: 'on_filtered_empty', label: '过滤后为空' },
] as const
function validateEnvironment(_rule: unknown, _value: unknown, callback: (error?: Error) => void) {
  callback(
    /^[A-Za-z_][A-Za-z0-9_]*$/.test(environmentName.value)
      ? undefined
      : new Error('请输入有效环境变量名称'),
  )
}
function submit() {
  if (!form.value) return
  const editorForm = form.value
  void save.run(async () => {
    if (!(await editorForm.validate(() => {}))) return
    const value = { ...draft.value }
    if ('api_key' in value && credentialMode.value !== 'keep')
      value.api_key =
        credentialMode.value === 'none' ? null : { kind: 'env', name: environmentName.value }
    if (props.initial) await resourcesApi.replace(props.kind, props.initial.id, value)
    else await resourcesApi.create(props.kind, value)
    ElMessage.success('资源已保存')
    emit('saved')
  })
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
    novalidate
    ref="form"
    :model="{ ...draft, environmentName }"
    label-position="top"
    @submit.prevent="submit"
  >
    <el-form-item label="资源 ID" prop="id" :rules="idRule">
      <el-input v-model="draft.id" :disabled="!!initial" />
    </el-form-item>
    <template v-if="'collector' in draft">
      <el-form-item label="采集器" prop="collector" :rules="idRule">
        <el-input v-model="draft.collector" placeholder="插件能力名称" />
      </el-form-item>
      <JsonField v-model="draft.setters" prop="setters" label="处理规则 (setters)" />
    </template>
    <template v-if="'provider' in draft">
      <el-form-item label="AI 提供商" prop="provider" :rules="idRule">
        <el-input v-model="draft.provider" placeholder="http" />
      </el-form-item>
      <el-form-item label="服务地址（可选）">
        <el-input
          :model-value="draft.base_url ?? ''"
          @update:model-value="draft.base_url = $event || null"
        />
      </el-form-item>
      <el-form-item label="凭据">
        <el-select v-model="credentialMode">
          <el-option value="keep" :label="initial ? '保留现有凭据' : '暂不配置'" />
          <el-option value="env" label="使用环境变量引用" />
          <el-option value="none" label="清除凭据" />
        </el-select>
      </el-form-item>
      <el-form-item
        v-if="credentialMode === 'env'"
        label="环境变量名称"
        prop="environmentName"
        :rules="{ validator: validateEnvironment }"
      >
        <el-input v-model="environmentName" placeholder="OPENAI_API_KEY" />
      </el-form-item>
      <JsonField v-model="models" prop="models" label="模型配置（模型名 → 参数对象）" />
      <el-form-item label="系统提示词">
        <el-input v-model="draft.system_prompt" type="textarea" :rows="3" />
      </el-form-item>
      <el-form-item label="重试次数">
        <el-input-number v-model="draft.retries" :min="0" :precision="0" />
      </el-form-item>
    </template>
    <template v-if="'channel' in draft">
      <el-form-item label="渠道能力名称" prop="channel" :rules="idRule">
        <el-input v-model="draft.channel" />
      </el-form-item>
      <el-form-item label="启用渠道"><el-switch v-model="draft.enabled" /></el-form-item>
    </template>
    <JsonField
      v-if="'options' in draft"
      v-model="draft.options"
      prop="options"
      label="插件参数 (options)"
    />
    <el-form-item v-if="'timeout' in draft" label="超时 / 秒">
      <el-input-number v-model="draft.timeout" :min="0.001" />
    </el-form-item>
    <template v-if="'on_error' in draft">
      <el-form-item label="处理模板 ID（可选）">
        <el-input
          :model-value="draft.template ?? ''"
          @update:model-value="draft.template = $event || null"
        />
      </el-form-item>
      <div class="form-grid">
        <el-form-item v-for="field in policyFields" :key="field.key" :label="field.label">
          <el-select v-model="draft[field.key]">
            <el-option
              v-for="policy in sourcePolicies"
              :key="policy.value"
              :value="policy.value"
              :label="policy.label"
            />
          </el-select>
        </el-form-item>
      </div>
    </template>
    <div class="flex justify-end gap-3">
      <el-button @click="emit('cancel')">取消</el-button>
      <el-button type="primary" native-type="submit" :loading="save.pending.value">
        保存资源
      </el-button>
    </div>
  </el-form>
</template>
