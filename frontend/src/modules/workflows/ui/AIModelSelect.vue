<script setup lang="ts">
import { computed } from 'vue'
import type { FormItemRule } from 'element-plus'
import type { AIConfig } from '@/modules/resources/public'
const props = withDefaults(
  defineProps<{
    ai: string | null
    model: string | null
    configs: readonly AIConfig[]
    optional?: boolean
    aiProp?: string
    modelProp?: string
  }>(),
  { optional: false, aiProp: '', modelProp: '' },
)
const emit = defineEmits<{
  'update:ai': [value: string | null]
  'update:model': [value: string | null]
}>()
const selected = computed(() => props.configs.find((item) => item.id === props.ai))
const models = computed(() => Object.keys(selected.value?.models ?? {}))
const invalidAI = computed(() => Boolean(props.ai && !selected.value))
const invalidModel = computed(() => Boolean(props.model && !models.value.includes(props.model)))
const noModels = computed(() => !props.configs.some((item) => Object.keys(item.models).length))
const aiRules = computed<FormItemRule[]>(() => [
  {
    validator: (_rule, value, callback) => {
      if (!value && props.optional && !props.model) return callback()
      if (!value) return callback(new Error('请选择供应商渠道'))
      if (invalidAI.value) return callback(new Error(`供应商渠道不存在：${props.ai}`))
      if (props.optional && !props.model)
        return callback(new Error('供应商渠道和渠道模型需要同时配置'))
      callback()
    },
  },
])
const modelRules = computed<FormItemRule[]>(() => [
  {
    validator: (_rule, value, callback) => {
      if (!value && props.optional && !props.ai) return callback()
      if (!value)
        return callback(
          new Error(props.optional ? '供应商渠道和渠道模型需要同时配置' : '请选择渠道模型'),
        )
      if (!props.ai) return callback(new Error('请选择供应商渠道'))
      if (invalidModel.value) return callback(new Error(`渠道模型不存在：${props.model}`))
      callback()
    },
  },
])
function changeAI(value: string | null) {
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
    >
      <el-select :model-value="ai" :clearable="optional" @update:model-value="changeAI">
        <el-option
          v-for="config in configs"
          :key="config.id"
          :value="config.id"
          :label="config.id"
        />
        <el-option v-if="invalidAI" :value="ai!" :label="`失效供应商渠道：${ai}`" disabled />
      </el-select>
      <span v-if="invalidAI" class="field-hint">供应商渠道不存在：{{ ai }}</span>
      <a v-if="noModels" href="/resources?kind=ai" target="_blank" rel="noopener">
        前往配置供应商渠道
      </a>
      <span v-if="noModels" class="field-hint">现有供应商渠道均未配置模型</span>
    </el-form-item>
    <el-form-item
      label="模型"
      :prop="modelProp || undefined"
      :rules="modelProp ? modelRules : undefined"
    >
      <el-select
        :model-value="model"
        :disabled="!ai || !models.length || invalidAI"
        @update:model-value="emit('update:model', $event)"
      >
        <el-option v-for="name in models" :key="name" :value="name" :label="name" />
        <el-option v-if="invalidModel" :value="model!" :label="`失效渠道模型：${model}`" disabled />
      </el-select>
    </el-form-item>
  </div>
</template>
