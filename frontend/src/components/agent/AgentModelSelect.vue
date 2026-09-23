<script setup lang="ts">
import { computed } from 'vue'
import type { AgentModel } from '@/api/agents'
import { groupAgentModels } from '@/domain/agentModels'

const props = defineProps<{
  modelValue: string
  models: AgentModel[]
  label: string
  optional?: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const groups = computed(() => groupAgentModels(props.models))
const unavailable = computed(
  () => props.modelValue && !props.models.some((item) => item.reference === props.modelValue),
)
</script>

<template>
  <el-select
    :model-value="modelValue"
    :aria-label="label"
    :clearable="optional"
    :disabled="disabled"
    placeholder="选择供应商渠道 / 模型"
    class="w-full"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-option-group v-for="group in groups" :key="group.channel" :label="group.channel">
      <el-option
        v-for="item in group.models"
        :key="item.reference"
        :value="item.reference"
        :label="`${item.ai} / ${item.model} · ${item.provider}`"
      />
    </el-option-group>
    <el-option v-if="unavailable" :value="modelValue" :label="`已失效：${modelValue}`" disabled />
  </el-select>
  <p v-if="unavailable" role="alert">所选供应商渠道模型已不可用，请重新选择。</p>
  <p v-if="!models.length" class="text-sm text-muted mt-2">暂无已配置的供应商渠道模型。</p>
  <a href="/resources?kind=ai" target="_blank" rel="noopener" class="text-sm">
    在资源配置中心管理供应商渠道
  </a>
</template>
