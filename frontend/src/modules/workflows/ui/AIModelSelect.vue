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
const emit = defineEmits<{ selection: [ai: string | null, model: string | null] }>()
const options = computed(() =>
  props.configs.flatMap((config) =>
    Object.keys(config.models).map((model) => ({
      value: JSON.stringify([config.id, model]),
      label: `${config.id} / ${model}`,
      ai: config.id,
      model,
    })),
  ),
)
const selected = computed(() =>
  props.ai && props.model ? JSON.stringify([props.ai, props.model]) : '',
)
const invalid = computed(
  () =>
    Boolean(props.ai || props.model) &&
    !options.value.some((item) => item.value === selected.value),
)
const rules = computed<FormItemRule[]>(() => [
  {
    validator: (_rule, _value, callback) => {
      if (!selected.value && props.optional && !props.ai && !props.model) return callback()
      if (!selected.value) return callback(new Error('请选择模型'))
      if (invalid.value) return callback(new Error('已选模型不在当前供应商渠道中'))
      callback()
    },
  },
])
function select(value: string) {
  const option = options.value.find((item) => item.value === value)
  emit('selection', option?.ai ?? null, option?.model ?? null)
}
</script>

<template>
  <el-form-item label="模型" :prop="aiProp || undefined" :rules="aiProp ? rules : undefined">
    <el-select
      :model-value="selected"
      :clearable="optional"
      :value-on-clear="''"
      filterable
      placeholder="选择已配置的供应商渠道模型"
      @update:model-value="select"
    >
      <el-option
        v-for="item in options"
        :key="item.value"
        :value="item.value"
        :label="item.label"
      />
      <el-option
        v-if="invalid"
        :value="selected"
        :label="`${ai || '未知渠道'} / ${model || '未知模型'}（不可用）`"
        disabled
      />
    </el-select>
    <span v-if="invalid" class="field-hint">所选模型已不可用，请重新选择。</span>
    <a v-if="!options.length" href="/resources?kind=ai" target="_blank" rel="noopener">
      配置供应商渠道模型
    </a>
  </el-form-item>
</template>
