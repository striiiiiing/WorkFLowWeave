<script setup lang="ts">
import type { SourceConfig } from '../model/public'
import { sourcePolicies } from '../model/source/forms'
defineProps<{ value: Readonly<SourceConfig> }>()
const emit = defineEmits<{ change: [value: Partial<SourceConfig>] }>()
const policyFields = [
  { key: 'on_error', label: '采集失败' },
  { key: 'on_empty', label: '采集为空' },
] as const
</script>
<template>
  <details aria-label="高级项" class="advanced-fields">
    <summary class="report-disclosure">高级配置</summary>
    <el-form-item label="超时 / 秒">
      <el-input-number
        :model-value="value.timeout"
        :min="0.001"
        :step="0.001"
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
    <div class="form-grid">
      <el-form-item label="单项 token 限额">
        <el-input-number
          :model-value="value.limits.item_tokens"
          :min="1"
          :precision="0"
          @update:model-value="
            emit('change', { limits: { ...value.limits, item_tokens: $event || null } })
          "
        />
      </el-form-item>
      <el-form-item label="字段 token 限额">
        <el-input-number
          :model-value="value.limits.field_tokens"
          :min="1"
          :precision="0"
          @update:model-value="
            emit('change', { limits: { ...value.limits, field_tokens: $event || null } })
          "
        />
      </el-form-item>
    </div>
  </details>
</template>
