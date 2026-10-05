<script setup lang="ts">
import { computed, ref } from 'vue'
import type { JsonObject } from '@/shared/types'
import ParameterField from '@/shared/schema/ParameterField.vue'

const models = defineModel<Record<string, JsonObject>>({ required: true })
const props = defineProps<{
  candidates: string[]
  loading: boolean
}>()
const emit = defineEmits<{ discover: [] }>()
const names = ref<string[]>([])
const query = ref('')
const addError = ref('')
const error = computed(
  () =>
    addError.value ||
    (names.value.length || query.value ? '请添加已选或正在填写的模型，或清空选择' : ''),
)
const expanded = ref<string[]>([])
const hasModel = (candidate: string) =>
  Object.prototype.hasOwnProperty.call(models.value, candidate)
const candidates = computed(() =>
  props.candidates.filter(
    (candidate) =>
      !hasModel(candidate) && candidate.toLowerCase().includes(query.value.toLowerCase()),
  ),
)
// These optional fields follow ai/options.py; unset fields use the provider's defaults.
const parameterSchema: JsonObject = {
  type: 'object',
  properties: {
    enable_thinking: { type: 'boolean', description: '是否启用思考；未设置时使用供应商默认行为。' },
    reasoning_effort: {
      type: 'string',
      enum: ['low', 'medium', 'high', 'xhigh', 'max'],
      description: '思考强度；关闭思考时请取消设置此字段。',
    },
  },
}
function add() {
  const selected = [...new Set([...names.value, query.value.trim()].filter(Boolean))]
  if (!selected.length) {
    addError.value = '请输入或选择模型名称'
    return
  }
  if (selected.some(hasModel)) {
    addError.value = '此渠道已添加该模型'
    return
  }
  models.value = { ...models.value, ...Object.fromEntries(selected.map((name) => [name, {}])) }
  names.value = []
  query.value = ''
  addError.value = ''
}
function filterModels(value: string) {
  query.value = value
  addError.value = ''
}
function selectModels() {
  query.value = ''
  addError.value = ''
}
function remove(selected: string) {
  models.value = Object.fromEntries(
    Object.entries(models.value).filter(([key]) => key !== selected),
  )
  expanded.value = expanded.value.filter((key) => key !== selected)
}
function update(selected: string, parameters: JsonObject) {
  models.value = { ...models.value, [selected]: parameters }
}
function toggle(selected: string) {
  expanded.value = expanded.value.includes(selected)
    ? expanded.value.filter((key) => key !== selected)
    : [...expanded.value, selected]
}
function validate(_rule: unknown, _value: unknown, callback: (error?: Error) => void) {
  callback(error.value ? new Error(error.value) : undefined)
}
</script>

<template>
  <section aria-label="渠道模型" class="mb-5">
    <div class="flex flex-wrap items-center justify-between gap-2 mb-2">
      <h3 class="font-semibold">渠道模型</h3>
    </div>
    <el-form-item prop="models" :rules="{ validator: validate }">
      <div class="flex gap-2 w-full min-w-0">
        <el-select
          v-model="names"
          multiple
          filterable
          allow-create
          default-first-option
          :reserve-keyword="false"
          :filter-method="filterModels"
          :loading="loading"
          loading-text="正在读取模型列表…"
          no-data-text="暂无可选模型，可输入模型名称"
          clearable
          aria-label="模型名称"
          placeholder="搜索或输入模型名称（可多选）"
          class="min-w-0 flex-1"
          @click.capture="emit('discover')"
          @change="selectModels"
        >
          <el-option
            v-for="candidate in candidates"
            :key="candidate"
            :label="candidate"
            :value="candidate"
          />
        </el-select>
        <el-button @click="add">添加模型</el-button>
      </div>
    </el-form-item>
    <p v-if="error" role="alert" class="text-red-700 text-sm mb-3">{{ error }}</p>
    <p v-if="!Object.keys(models).length" class="muted text-sm">
      尚未添加模型。可以先保存渠道，稍后再添加。
    </p>
    <div
      v-for="(parameters, selected) in models"
      :key="selected"
      class="border rounded-lg p-3 mb-3"
    >
      <div class="flex flex-wrap items-center justify-between gap-2">
        <span class="mono break-all">{{ selected }}</span>
        <div class="flex gap-2">
          <el-button :aria-expanded="expanded.includes(selected)" @click="toggle(selected)">
            {{ expanded.includes(selected) ? '收起参数' : '配置参数' }}
          </el-button>
          <el-button
            type="danger"
            plain
            :aria-label="`移除模型 ${selected}`"
            @click="remove(selected)"
          >
            移除
          </el-button>
        </div>
      </div>
      <div v-show="expanded.includes(selected)" class="mt-3">
        <ParameterField
          :model-value="parameters"
          :prop="['models', selected]"
          label="额外请求参数（extra_body）"
          :schema="parameterSchema"
          @update:model-value="update(selected, $event)"
        />
      </div>
    </div>
  </section>
</template>
