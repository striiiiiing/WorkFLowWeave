<script setup lang="ts">
import { computed, ref, toRaw, watch, nextTick } from 'vue'
import { ElMessage, type FormInstance } from 'element-plus'
import { resourcesApi } from '@/api/resources'
import { useAsyncTask } from '@/shared/async/useAsyncTask'
import {
  createResource,
  credentialPropertyNames,
  generatedResourceId,
  type EditableKind,
  type EditableResource,
} from '@/domain/resources'
import { optionSchema } from '@/shared/schema/capabilities'
import { idRule, sourcePolicies } from '@/domain/forms'
import ParameterField from '@/shared/schema/ParameterField.vue'
import AIProviderEditor from './AIProviderEditor.vue'
import CredentialEditor from './CredentialEditor.vue'
import type { Credential, JsonObject } from '@/types'
import { systemApi } from '@/api/system'
import { useQuery } from '@/shared/async/useQuery'
const props = defineProps<{ kind: EditableKind; initial?: EditableResource; local?: boolean }>()
const emit = defineEmits<{ saved: [value?: EditableResource]; cancel: [] }>()
const initialDraft = props.initial
  ? structuredClone(toRaw(props.initial))
  : createResource(props.kind)
const draft = ref(initialDraft)
const generatedId = ref(!props.initial)
const form = ref<FormInstance>()
const save = useAsyncTask()
const advanced = ref(false)
const {
  data: plugins,
  error: pluginError,
  pending: pluginsPending,
  refresh: refreshPlugins,
} = useQuery((signal) => (props.kind === 'ai' ? Promise.resolve([]) : systemApi.plugins(signal)))
const capabilities = computed(
  () =>
    plugins.value?.filter(
      (item) => item.kind === (props.kind === 'channels' ? 'channel' : 'collector'),
    ) ?? [],
)
const capabilityName = computed(() =>
  'collector' in draft.value
    ? draft.value.collector
    : 'channel' in draft.value
      ? draft.value.channel
      : '',
)
const capability = computed(() =>
  capabilities.value.find((item) => item.name === capabilityName.value),
)
const optionParameterSchema = computed(() =>
  optionSchema(capability.value?.options_schema, 'resource'),
)
const credentialNames = computed(() => credentialPropertyNames(capability.value?.options_schema))
const credentialEditors = new Map<string, InstanceType<typeof CredentialEditor>>()
function setCredentialEditor(name: string, editor: unknown) {
  if (editor && typeof editor === 'object' && 'prepare' in editor) {
    credentialEditors.set(name, editor as InstanceType<typeof CredentialEditor>)
  } else {
    credentialEditors.delete(name)
  }
}
function credentialValue(name: string): Credential | null {
  if (!('options' in draft.value)) return null
  const value = draft.value.options[name]
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Credential) : null
}
function fieldLabel(schema: JsonObject | undefined, name: string): string {
  const properties = (schema?.properties ?? {}) as Record<string, JsonObject>
  const description = properties[name]?.description
  return typeof description === 'string' && description.trim() ? description : name
}
function updateCredential(name: string, value: Credential | null) {
  if (!('options' in draft.value)) return
  if (value === null) {
    const next = { ...draft.value.options }
    delete next[name]
    draft.value.options = next
    return
  }
  draft.value.options = { ...draft.value.options, [name]: value }
}
function updateId(value: string) {
  draft.value.id = value
  generatedId.value = false
}
watch(capabilityName, (next, previous) => {
  if (next === previous) return
  if ('channel' in draft.value) draft.value.agent_enabled = false
  if (!props.initial && generatedId.value) {
    draft.value.id = generatedResourceId(capability.value?.id_prefix)
  }
  if ('options' in draft.value) {
    draft.value.options = {}
    if ('setters' in draft.value) draft.value.setters = {}
    if ('template' in draft.value) draft.value.template = null
  } else if ('setters' in draft.value) {
    draft.value.setters = {}
  }
})
const policyFields = [
  { key: 'on_error', label: '采集失败' },
  { key: 'on_missing', label: '来源缺失' },
  { key: 'on_empty', label: '采集为空' },
  { key: 'on_filtered_empty', label: '过滤后为空' },
] as const
function submit() {
  if (!form.value) return
  const editorForm = form.value
  void save.run(async () => {
    if ('options' in draft.value) {
      for (const name of credentialNames.value) {
        const editor = credentialEditors.get(name)
        if (editor) draft.value.options[name] = await editor.prepare()
      }
    }
    await nextTick()
    if (!(await editorForm.validate(() => {}))) return
    const value = structuredClone(toRaw(draft.value))
    value.id ||= generatedResourceId(capability.value?.id_prefix)
    if (props.local) {
      emit('saved', value)
      return
    }
    const saved = props.initial
      ? await resourcesApi.replace(props.kind, props.initial.id, value)
      : await resourcesApi.create(props.kind, value)
    ElMessage.success('资源已保存')
    emit('saved', saved)
  })
}
</script>
<template>
  <AIProviderEditor
    v-if="kind === 'ai'"
    :initial="initial && 'provider' in initial ? initial : undefined"
    @saved="emit('saved', $event)"
    @cancel="emit('cancel')"
  />
  <template v-else>
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
      :model="draft"
      :disabled="save.pending.value"
      label-position="top"
      @submit.prevent.stop="submit"
    >
      <template v-if="'collector' in draft">
        <h3 class="font-semibold mb-4">基础信息</h3>
        <el-form-item label="数据源名称">
          <el-input v-model="draft.display_name" placeholder="便于识别的名称，如应用运行日志" />
        </el-form-item>
        <el-form-item label="用途说明">
          <el-input v-model="draft.description" placeholder="说明此数据源采集什么、用于哪些分析" />
        </el-form-item>
      </template>
      <el-form-item label="资源编号" prop="id" :rules="{ ...idRule, required: false }">
        <el-input
          :model-value="draft.id"
          :disabled="!!initial"
          placeholder="可自行填写；留空则自动生成"
          @update:model-value="updateId"
        />
      </el-form-item>
      <el-alert v-if="pluginError" :title="pluginError" type="error" :closable="false" />
      <el-button v-if="pluginError" @click="refreshPlugins">重新加载插件选项</el-button>
      <p v-if="capability" class="muted mb-4">{{ capability.description }}</p>
      <el-alert
        v-if="capabilityName && plugins && !capability"
        title="当前插件未注册，请检查插件加载状态或选择已注册能力。"
        type="error"
        :closable="false"
      />
      <template v-if="'collector' in draft">
        <el-form-item v-if="'enabled' in draft" label="启用数据源">
          <el-switch v-model="draft.enabled" />
        </el-form-item>
        <el-form-item label="采集器" prop="collector" :rules="idRule">
          <el-select
            v-model="draft.collector"
            filterable
            placeholder="选择采集器"
            :loading="pluginsPending"
            :disabled="local"
          >
            <el-option
              v-for="item in capabilities"
              :key="item.name"
              :value="item.name"
              :label="item.name"
            />
            <el-option
              v-if="draft.collector && !capability"
              :value="draft.collector"
              :label="draft.collector + '（未注册）'"
              disabled
            />
          </el-select>
        </el-form-item>
      </template>
      <template v-if="'channel' in draft">
        <el-form-item label="渠道能力名称" prop="channel" :rules="idRule">
          <el-select
            v-model="draft.channel"
            filterable
            placeholder="选择渠道"
            :loading="pluginsPending"
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
        <el-form-item label="启用渠道"><el-switch v-model="draft.enabled" /></el-form-item>
        <el-form-item
          v-if="capability?.capabilities.includes('conversation')"
          label="接入 Agent 对话"
        >
          <el-switch v-model="draft.agent_enabled" />
        </el-form-item>
      </template>
      <ParameterField
        v-if="'options' in draft"
        v-model="draft.options"
        :excluded-properties="credentialNames"
        prop="options"
        :label="
          'on_error' in draft
            ? local
              ? '独立采集配置 (options)'
              : '数据源共用配置 (options)'
            : '插件参数 (options)'
        "
        :key="`options-${capabilityName}`"
        :schema="optionParameterSchema"
      />
      <CredentialEditor
        v-for="name in credentialNames"
        :key="`${capabilityName}-${name}`"
        :ref="(editor) => setCredentialEditor(name, editor)"
        :model-value="credentialValue(name)"
        :label="fieldLabel(capability?.options_schema, name)"
        @update:model-value="updateCredential(name, $event)"
      />
      <ParameterField
        v-if="'setters' in draft"
        v-model="draft.setters"
        prop="setters"
        label="处理规则 (setters)"
        :key="`setters-${capabilityName}`"
        :schema="capability?.setters_schema ?? undefined"
      />
      <el-form-item label="高级模式"><el-switch v-model="advanced" /></el-form-item>
      <el-form-item v-if="advanced && 'timeout' in draft" label="超时 / 秒">
        <el-input-number v-model="draft.timeout" :min="0.001" />
      </el-form-item>
      <template v-if="advanced && 'on_error' in draft">
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
          {{ local ? '应用到当前工作流' : '保存资源' }}
        </el-button>
      </div>
    </el-form>
  </template>
</template>
