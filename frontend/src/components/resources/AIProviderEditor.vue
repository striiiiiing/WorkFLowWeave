<script setup lang="ts">
import { computed, ref, toRaw, watch } from 'vue'
import { ElMessage, type FormInstance } from 'element-plus'
import { resourcesApi } from '@/api/resources'
import { useAsyncTask } from '@/composables/useAsyncTask'
import { createResource } from '@/domain/resources'
import { idRule } from '@/domain/forms'
import type { AIConfig } from '@/types'
import AIModelList from './AIModelList.vue'

const props = defineProps<{ initial?: AIConfig }>()
const emit = defineEmits<{ saved: [value: AIConfig]; cancel: [] }>()
const initial = props.initial
  ? structuredClone(toRaw(props.initial))
  : (createResource('ai') as AIConfig)
const draft = ref(initial)
const persisted = ref(props.initial ? structuredClone(initial) : undefined)
const form = ref<FormInstance>()
const save = useAsyncTask()
const health = useAsyncTask()
const advanced = ref(false)
const plaintext = ref('')
const credentialMode = ref<'keep' | 'input' | 'env' | 'none'>(props.initial ? 'keep' : 'input')
const environmentName = ref(initial.api_key?.kind === 'env' ? initial.api_key.name : '')
const discovered = ref<string[]>([])
const checked = ref(false)
const busy = computed(() => save.pending.value || health.pending.value)
const connectionChanged = computed(
  () =>
    !persisted.value ||
    draft.value.base_url !== persisted.value.base_url ||
    draft.value.provider !== persisted.value.provider ||
    JSON.stringify(draft.value.api_key) !== JSON.stringify(persisted.value.api_key) ||
    credentialMode.value !== 'keep',
)
const healthHint = computed(() => {
  if (!persisted.value) return '保存渠道后，可在这里独立检查健康。'
  if (connectionChanged.value) return '连接配置已修改，请先保存，再检查健康。'
  return '检查已保存的连接能否获取模型列表，不会调用模型进行分析。'
})
watch(
  () => [
    draft.value.base_url,
    draft.value.provider,
    credentialMode.value,
    environmentName.value,
    plaintext.value,
  ],
  () => {
    checked.value = false
    discovered.value = []
    health.error.value = ''
  },
)
function validateEnvironment(_rule: unknown, _value: unknown, callback: (error?: Error) => void) {
  callback(
    /^[A-Za-z_][A-Za-z0-9_]*$/.test(environmentName.value)
      ? undefined
      : new Error('请输入有效环境变量名称'),
  )
}
function checkHealth() {
  if (!persisted.value || connectionChanged.value || busy.value) return
  const id = persisted.value.id
  checked.value = false
  discovered.value = []
  void health.run(async () => {
    discovered.value = await resourcesApi.checkAIConnection(id)
    checked.value = true
  })
}
function submit() {
  if (!form.value || busy.value) return
  const editorForm = form.value
  void save.run(async () => {
    if (!(await editorForm.validate(() => {}))) {
      throw new Error('请检查表单中的错误；模型参数错误可在“配置参数”中修改。')
    }
    // Only top-level fields change here; the HTTP boundary serializes nested Vue proxies as JSON.
    const value = { ...draft.value }
    value.id ||= crypto.randomUUID()
    if (credentialMode.value === 'input') {
      value.api_key = await resourcesApi.protectCredential(plaintext.value)
      draft.value.api_key = value.api_key
      plaintext.value = ''
      credentialMode.value = 'keep'
    } else if (credentialMode.value !== 'keep') {
      value.api_key =
        credentialMode.value === 'none' ? null : { kind: 'env', name: environmentName.value }
    }
    const result = persisted.value
      ? await resourcesApi.replace('ai', persisted.value.id, value)
      : await resourcesApi.create('ai', value)
    draft.value = structuredClone(result)
    persisted.value = structuredClone(result)
    credentialMode.value = 'keep'
    ElMessage.success('供应商渠道已保存')
    emit('saved', result)
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
    ref="form"
    novalidate
    :model="{ ...draft, plaintext, environmentName }"
    :disabled="busy"
    label-position="top"
    @submit.prevent="submit"
  >
    <h3 class="font-semibold mb-3">连接配置</h3>
    <el-form-item label="API 格式" prop="provider" :rules="idRule">
      <el-radio-group v-model="draft.provider">
        <el-radio :value="draft.provider === 'http' ? 'http' : 'openai_compatible_api'">
          OpenAI Compatible API
        </el-radio>
      </el-radio-group>
    </el-form-item>
    <el-form-item
      label="服务地址"
      prop="base_url"
      :rules="{ required: true, message: '请输入服务地址' }"
    >
      <el-input
        :model-value="draft.base_url ?? ''"
        placeholder="https://api.openai.com/v1"
        @update:model-value="draft.base_url = $event || null"
      />
    </el-form-item>
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
    <section aria-label="渠道健康检查" class="mb-5">
      <el-button :loading="health.pending.value" :disabled="connectionChanged" @click="checkHealth">
        检查健康
      </el-button>
      <p class="muted text-sm mt-2">{{ healthHint }}</p>
      <el-alert
        v-if="health.error.value"
        :title="health.error.value"
        type="error"
        :closable="false"
        show-icon
      />
      <el-alert
        v-else-if="checked"
        :title="`连接正常，发现 ${discovered.length} 个模型。请在下方选择添加。`"
        type="success"
        :closable="false"
        show-icon
      />
    </section>
    <AIModelList v-model="draft.models" :candidates="discovered" />
    <el-form-item label="高级模式"><el-switch v-model="advanced" /></el-form-item>
    <div v-if="advanced">
      <el-form-item
        label="资源 ID（留空自动生成）"
        prop="id"
        :rules="{ ...idRule, required: false }"
      >
        <el-input v-model="draft.id" :disabled="!!persisted" />
      </el-form-item>
      <div class="form-grid">
        <el-form-item
          label="超时 / 秒"
          prop="timeout"
          :rules="{ required: true, type: 'number', min: 0.001, message: '请输入大于零的超时秒数' }"
        >
          <el-input-number v-model="draft.timeout" :min="0.001" />
        </el-form-item>
        <el-form-item
          label="重试次数"
          prop="retries"
          :rules="{ required: true, type: 'integer', min: 0, message: '请输入非负整数' }"
        >
          <el-input-number v-model="draft.retries" :min="0" :precision="0" />
        </el-form-item>
      </div>
    </div>
    <div class="flex justify-end gap-3">
      <el-button @click="emit('cancel')">关闭</el-button>
      <el-button type="primary" native-type="submit" :loading="save.pending.value">
        保存渠道
      </el-button>
    </div>
  </el-form>
</template>
