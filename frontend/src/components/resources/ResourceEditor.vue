<script setup lang="ts">
import { computed, ref, toRaw } from 'vue'
import { ElMessage, type FormInstance } from 'element-plus'
import { resourcesApi } from '@/api/resources'
import { useAsyncTask } from '@/composables/useAsyncTask'
import { createResource, type EditableKind, type EditableResource } from '@/domain/resources'
import { optionSchema, partialSchema } from '@/domain/capabilities'
import { idRule, sourcePolicies } from '@/domain/forms'
import ParameterField from '@/components/common/ParameterField.vue'
import { systemApi } from '@/api/system'
import { useQuery } from '@/composables/useQuery'
const props = defineProps<{ kind: EditableKind; initial?: EditableResource }>()
const emit = defineEmits<{ saved: []; cancel: [] }>()
const draft = ref(
  props.initial ? structuredClone(toRaw(props.initial)) : createResource(props.kind),
)
const form = ref<FormInstance>()
const save = useAsyncTask()
const advanced = ref(false)
const plaintext = ref('')
const credentialMode = ref<'keep' | 'env' | 'none' | 'input'>(props.initial ? 'keep' : 'input')
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
    const value = { ...draft.value, id: draft.value.id || crypto.randomUUID() }
    if ('api_key' in value && credentialMode.value !== 'keep') {
      if (credentialMode.value === 'input') {
        value.api_key = await resourcesApi.protectCredential(plaintext.value)
        draft.value = { ...value }
        plaintext.value = ''
        credentialMode.value = 'keep'
      } else {
        value.api_key =
          credentialMode.value === 'none' ? null : { kind: 'env', name: environmentName.value }
      }
    }
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
    :model="{ ...draft, environmentName, plaintext }"
    label-position="top"
    @submit.prevent="submit"
  >
    <el-form-item label="高级模式"><el-switch v-model="advanced" /></el-form-item>
    <el-form-item
      v-if="advanced"
      label="资源 ID（留空自动生成）"
      prop="id"
      :rules="{ ...idRule, required: false }"
    >
      <el-input v-model="draft.id" :disabled="!!initial" />
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
      <ParameterField
        v-model="draft.setters"
        prop="setters"
        label="处理规则 (setters)"
        :schema="
          kind === 'setters'
            ? partialSchema(capability?.setters_schema)
            : (capability?.setters_schema ?? undefined)
        "
      />
    </template>
    <template v-if="'provider' in draft">
      <el-form-item label="AI 提供商" prop="provider" :rules="idRule">
        <el-input v-model="draft.provider" placeholder="OpenAI" />
      </el-form-item>
      <el-form-item
        label="服务地址"
        prop="base_url"
        :rules="{ required: draft.provider === 'http', message: '请输入 HTTP 服务地址' }"
      >
        <el-input
          :model-value="draft.base_url ?? ''"
          placeholder="https://api.openai.com/v1"
          @update:model-value="draft.base_url = $event || null"
        />
      </el-form-item>
      <p class="muted mb-4">
        OpenAI 兼容服务（包括 AxonHub）请选择 provider 为 <code>http</code>，并填写包含
        <code>/v1</code> 的服务地址。
      </p>
      <el-form-item label="凭据">
        <el-select v-model="credentialMode">
          <el-option value="keep" :label="draft.api_key ? '保留现有凭据' : '暂不配置'" />
          <el-option value="input" label="输入 API 密钥（加密保存）" />
          <el-option value="env" label="使用环境变量引用" />
          <el-option value="none" label="清除凭据" />
        </el-select>
      </el-form-item>
      <el-form-item
        v-if="credentialMode === 'input'"
        label="API 密钥"
        prop="plaintext"
        :rules="{ required: true, message: '请输入 API 密钥，或选择暂不配置' }"
      >
        <el-input v-model="plaintext" type="password" show-password autocomplete="new-password" />
      </el-form-item>
      <el-form-item
        v-if="credentialMode === 'env'"
        label="环境变量名称"
        prop="environmentName"
        :rules="{ validator: validateEnvironment }"
      >
        <el-input v-model="environmentName" placeholder="OPENAI_API_KEY" />
      </el-form-item>
      <ParameterField
        v-if="advanced"
        v-model="models"
        prop="models"
        label="模型配置（模型名 → 参数对象）"
        :schema="{ type: 'object', additionalProperties: { type: 'object' } }"
      />
      <el-form-item v-if="advanced" label="重试次数">
        <el-input-number v-model="draft.retries" :min="0" :precision="0" />
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
    </template>
    <ParameterField
      v-if="'options' in draft"
      v-model="draft.options"
      prop="options"
      label="插件参数 (options)"
      :schema="optionSchema(capability?.options_schema, 'resource')"
    />
    <el-form-item v-if="advanced && 'timeout' in draft" label="超时 / 秒">
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
