<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, type FormInstance } from 'element-plus'
import type { AIConfig } from '../model/types'
import { useAIProviderEditor } from '../composables/useAIProviderEditor'
import { idRule } from '../model/forms'
import AIModelList from './AIModelList.vue'
const props = defineProps<{ initial?: AIConfig }>()
const emit = defineEmits<{ saved: [value: AIConfig]; cancel: [] }>()
const {
  draft,
  updateConnection,
  updateId,
  updateModels,
  updateAdvanced,
  persisted,
  save,
  health,
  plaintext,
  credentialMode,
  environmentName,
  discovered,
  checked,
  busy,
  modelTest,
  testedModel,
  connectionChanged,
  checkHealth,
  testModel,
  submit: saveDraft,
} = useAIProviderEditor(props)
const form = ref<FormInstance>()
const healthHint = computed(() => {
  if (!persisted.value) return '保存渠道后，可在这里独立检查健康。'
  if (connectionChanged.value) return '连接配置已修改，请先保存，再检查健康。'
  return '检查已保存的连接能否获取模型列表，不会调用模型进行分析。'
})
function validateEnvironment(_rule: unknown, _value: unknown, callback: (error?: Error) => void) {
  callback(
    /^[A-Za-z_][A-Za-z0-9_]*$/.test(environmentName.value)
      ? undefined
      : new Error('请输入有效环境变量名称'),
  )
}

async function submit() {
  const result = await saveDraft(async () => (await form.value?.validate(() => {})) ?? false)
  if (result.status === 'success') {
    ElMessage.success('供应商渠道已保存')
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
    :model="{ ...draft, plaintext, environmentName }"
    :disabled="busy"
    label-position="top"
    @submit.prevent="submit"
  >
    <h3 class="font-semibold mb-3">连接配置</h3>
    <el-form-item label="API 格式" prop="provider" :rules="idRule">
      <el-radio-group
        :model-value="draft.provider"
        @update:model-value="updateConnection({ provider: String($event) })"
      >
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
        @update:model-value="updateConnection({ base_url: $event || null })"
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
    <section aria-label="渠道模型发现" class="mb-5">
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
      <el-alert
        v-if="modelTest.error.value"
        :title="modelTest.error.value"
        type="error"
        :closable="false"
        show-icon
      />
      <el-alert
        v-else-if="testedModel"
        :title="`模型“${testedModel}”测试成功，已收到正常响应。`"
        type="success"
        :closable="false"
        show-icon
      />
    </section>
    <AIModelList
      :model-value="draft.models"
      @update:model-value="updateModels"
      :candidates="discovered"
      :testing="health.pending.value"
      :model-testing="modelTest.pending.value"
      :test-disabled="connectionChanged || !persisted"
      @discover="checkHealth"
      @test="testModel"
    />
    <el-form-item label="资源编号" prop="id" :rules="{ ...idRule, required: false }">
      <el-input
        :model-value="draft.id"
        @update:model-value="updateId"
        :disabled="!!persisted"
        placeholder="可自行填写；留空则自动生成"
      />
    </el-form-item>
    <details class="advanced-fields">
      <summary class="report-disclosure">高级配置</summary>
      <div class="form-grid">
        <el-form-item
          label="超时 / 秒"
          prop="timeout"
          :rules="{ required: true, type: 'number', min: 0.001, message: '请输入大于零的超时秒数' }"
        >
          <el-input-number
            :model-value="draft.timeout"
            @update:model-value="updateAdvanced({ timeout: $event })"
            :min="0.001"
          />
        </el-form-item>
        <el-form-item
          label="重试次数"
          prop="retries"
          :rules="{ required: true, type: 'integer', min: 0, message: '请输入非负整数' }"
        >
          <el-input-number
            :model-value="draft.retries"
            @update:model-value="updateAdvanced({ retries: $event })"
            :min="0"
            :precision="0"
          />
        </el-form-item>
      </div>
    </details>
    <div class="flex justify-end gap-3">
      <el-button @click="emit('cancel')">关闭</el-button>
      <el-button type="primary" native-type="submit" :loading="save.pending.value">
        保存渠道
      </el-button>
    </div>
  </el-form>
</template>
