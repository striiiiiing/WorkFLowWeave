<script setup lang="ts">
import { computed } from 'vue'
import type { FormItemRule } from 'element-plus'
import type { AIConfig } from '@/types'

interface Props {
  ai: string | null
  model: string | null
  configs: AIConfig[]
  optional?: boolean
  aiProp?: string
  modelProp?: string
}
const props = withDefaults(defineProps<Props>(), {
  optional: false,
  aiProp: '',
  modelProp: '',
})
const emit = defineEmits<{
  'update:ai': [value: string | null]
  'update:model': [value: string | null]
}>()

const selectedConfig = computed(() => props.configs.find((item) => item.id === props.ai))
const models = computed(() => Object.keys(selectedConfig.value?.models ?? {}))
const hasModels = (config: AIConfig) => Object.keys(config.models).length > 0
const hasConfiguredModels = computed(() => props.configs.some(hasModels))
const invalidAI = computed(() => Boolean(props.ai && !selectedConfig.value))
const invalidModel = computed(() =>
  Boolean(props.model && (!selectedConfig.value || !models.value.includes(props.model))),
)

const aiError = computed(() => (invalidAI.value ? `供应商渠道不存在：${props.ai}` : undefined))
const modelError = computed(() => {
  if (!invalidModel.value || !props.model) return undefined
  if (!selectedConfig.value) return `无法校验渠道模型“${props.model}”的供应商渠道归属`
  return `渠道模型“${props.model}”不属于供应商渠道“${selectedConfig.value.id}”`
})

function validateAI(
  _rule: unknown,
  value: string | null,
  callback: (error?: string | Error) => void,
) {
  if (!value && props.optional && !props.model) return callback()
  if (!value) return callback('请选择供应商渠道')
  if (invalidAI.value) return callback(aiError.value)
  if (props.optional && !props.model) return callback('供应商渠道和渠道模型需要同时配置')
  callback()
}

function validateModel(
  _rule: unknown,
  value: string | null,
  callback: (error?: string | Error) => void,
) {
  if (!value && props.optional && !props.ai) return callback()
  if (!value)
    return callback(props.optional ? '供应商渠道和渠道模型需要同时配置' : '请选择渠道模型')
  if (!props.ai) return callback('请选择供应商渠道')
  if (invalidModel.value) return callback(modelError.value)
  callback()
}

const aiRules = computed<FormItemRule[]>(() => [{ validator: validateAI, trigger: 'change' }])
const modelRules = computed<FormItemRule[]>(() => [{ validator: validateModel, trigger: 'change' }])

function changeAI(value: string) {
  emit('update:ai', value || null)
  emit('update:model', null)
}
</script>
<template>
  <div class="form-grid">
    <el-form-item
      label="供应商渠道"
      :prop="aiProp || undefined"
      :rules="aiProp ? aiRules : undefined"
      :error="aiError"
    >
      <el-select
        :model-value="ai"
        :clearable="optional"
        placeholder="选择供应商渠道"
        @update:model-value="changeAI"
      >
        <el-option
          v-for="config in configs"
          :key="config.id"
          :value="config.id"
          :label="hasModels(config) ? config.id : `${config.id}（未配置模型）`"
          :disabled="!hasModels(config)"
        />
        <el-option v-if="invalidAI" :value="ai!" :label="`失效供应商渠道：${ai}`" disabled />
      </el-select>
    </el-form-item>
    <el-form-item
      label="模型"
      :prop="modelProp || undefined"
      :rules="modelProp ? modelRules : undefined"
      :error="modelError"
    >
      <el-select
        :model-value="model"
        :disabled="!ai || !models.length || invalidAI"
        placeholder="选择模型"
        @update:model-value="$emit('update:model', $event)"
      >
        <el-option v-for="name in models" :key="name" :value="name" :label="name" />
        <el-option v-if="invalidModel" :value="model!" :label="`失效渠道模型：${model}`" disabled />
      </el-select>
      <p v-if="!configs.length" class="muted">
        尚未配置供应商渠道模型，
        <a href="/resources?kind=ai" target="_blank" rel="noopener">前往配置供应商渠道</a>
      </p>
      <p v-else-if="!hasConfiguredModels" class="muted">
        现有供应商渠道均未配置模型，
        <a href="/resources?kind=ai" target="_blank" rel="noopener">前往配置供应商渠道</a>
      </p>
      <p v-else-if="ai && selectedConfig && !models.length" class="muted">
        当前供应商渠道尚未配置模型，
        <a href="/resources?kind=ai" target="_blank" rel="noopener">前往配置供应商渠道</a>
      </p>
      <p v-else-if="ai" class="muted">归属渠道：{{ ai }}</p>
    </el-form-item>
  </div>
</template>
