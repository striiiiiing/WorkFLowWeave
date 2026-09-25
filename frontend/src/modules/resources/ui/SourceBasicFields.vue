<script setup lang="ts">
import type { SourceConfig } from '../model/types'
import type { SchemaCapability } from '@/shared/schema/types'
import { idRule } from '../model/forms'
defineProps<{
  value: Readonly<SourceConfig>
  initial: boolean
  independent: boolean
  capabilities: readonly SchemaCapability[]
}>()
const emit = defineEmits<{
  basic: [value: Partial<SourceConfig>]
  id: [value: string]
  collector: [value: string]
}>()
</script>
<template>
  <section aria-label="基础信息">
    <h3 class="font-semibold mb-4">基础信息</h3>
    <el-form-item label="数据源名称">
      <el-input
        :model-value="value.display_name"
        placeholder="便于识别的名称，如应用运行日志"
        @update:model-value="emit('basic', { display_name: $event })"
      />
    </el-form-item>
    <el-form-item label="用途说明">
      <el-input
        :model-value="value.description"
        placeholder="说明此数据源采集什么、用于哪些分析"
        @update:model-value="emit('basic', { description: $event })"
      />
    </el-form-item>
    <el-form-item label="资源编号" prop="id" :rules="{ ...idRule, required: false }">
      <el-input
        :model-value="value.id"
        :disabled="initial"
        placeholder="可自行填写；留空则自动生成"
        @update:model-value="emit('id', $event)"
      />
    </el-form-item>
    <el-form-item label="启用数据源">
      <el-switch
        :model-value="value.enabled"
        @update:model-value="emit('basic', { enabled: Boolean($event) })"
      />
    </el-form-item>
    <el-form-item label="采集器" prop="collector" :rules="idRule">
      <el-select
        :model-value="value.collector"
        filterable
        placeholder="选择采集器"
        :disabled="independent"
        @update:model-value="emit('collector', $event)"
      >
        <el-option
          v-for="item in capabilities"
          :key="item.name"
          :value="item.name"
          :label="item.name"
        />
        <el-option
          v-if="value.collector && !capabilities.some((item) => item.name === value.collector)"
          :value="value.collector"
          :label="value.collector + '（未注册）'"
          disabled
        />
      </el-select>
    </el-form-item>
  </section>
</template>
