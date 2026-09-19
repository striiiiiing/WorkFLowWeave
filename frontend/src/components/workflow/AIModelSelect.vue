<script setup lang="ts">
import { computed } from 'vue'
import type { AIConfig } from '@/types'
const props = defineProps<{
  ai: string | null
  model: string | null
  configs: AIConfig[]
  optional?: boolean
}>()
const emit = defineEmits<{
  'update:ai': [value: string | null]
  'update:model': [value: string | null]
}>()
const models = computed(() =>
  Object.keys(props.configs.find((item) => item.id === props.ai)?.models ?? {}),
)
function changeAI(value: string) {
  emit('update:ai', value || null)
  emit('update:model', null)
}
</script>
<template>
  <div class="form-grid">
    <el-form-item label="AI 配置">
      <el-select
        :model-value="ai"
        :clearable="optional"
        placeholder="选择 AI 配置"
        @update:model-value="changeAI"
      >
        <el-option
          v-for="config in configs"
          :key="config.id"
          :value="config.id"
          :label="config.id"
        />
      </el-select>
    </el-form-item>
    <el-form-item label="模型">
      <el-select
        :model-value="model"
        :disabled="!ai"
        placeholder="选择模型"
        @update:model-value="$emit('update:model', $event)"
      >
        <el-option v-for="name in models" :key="name" :value="name" :label="name" />
      </el-select>
    </el-form-item>
  </div>
</template>
