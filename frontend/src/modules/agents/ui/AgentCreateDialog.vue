<script setup lang="ts">
import type { AgentModel } from '../model/public'
import AgentModelSelect from './AgentModelSelect.vue'

defineProps<{
  modelValue: boolean
  model: string
  models: AgentModel[]
  pending: boolean
  error: string
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'update:model': [value: string]
  create: []
}>()
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="创建 Agent 分析会话"
    width="min(90vw, 500px)"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-form label-position="top">
      <el-form-item label="供应商渠道 / 模型">
        <AgentModelSelect
          :model-value="model"
          :models="models"
          label="新会话模型"
          @update:model-value="emit('update:model', $event)"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button
        type="primary"
        :loading="pending"
        :disabled="!models.some((item) => item.reference === model)"
        @click="emit('create')"
      >
        确认创建
      </el-button>
    </template>
  </el-dialog>
</template>
