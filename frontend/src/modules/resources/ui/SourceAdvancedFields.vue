<script setup lang="ts">
import type { SourceConfig } from '../model/types'
import { sourcePolicies } from '../model/forms'
defineProps<{ value: Readonly<SourceConfig> }>()
const emit = defineEmits<{ change: [value: Partial<SourceConfig>] }>()
const policyFields = [
  { key: 'on_error', label: '采集失败' },
  { key: 'on_missing', label: '来源缺失' },
  { key: 'on_empty', label: '采集为空' },
  { key: 'on_filtered_empty', label: '过滤后为空' },
] as const
</script>
<template>
  <details aria-label="高级项" class="advanced-fields">
    <summary class="report-disclosure">高级配置</summary>
    <el-form-item label="超时 / 秒">
      <el-input-number
        :model-value="value.timeout"
        :min="0.001"
        @update:model-value="emit('change', { timeout: $event })"
      />
    </el-form-item>
    <div class="form-grid">
      <el-form-item v-for="field in policyFields" :key="field.key" :label="field.label">
        <el-select
          :model-value="value[field.key]"
          @update:model-value="emit('change', { [field.key]: $event })"
        >
          <el-option
            v-for="policy in sourcePolicies"
            :key="policy.value"
            :value="policy.value"
            :label="policy.label"
          />
        </el-select>
      </el-form-item>
    </div>
    <p v-if="value.template" class="muted">沿用处理模板：{{ value.template }}</p>
  </details>
</template>
