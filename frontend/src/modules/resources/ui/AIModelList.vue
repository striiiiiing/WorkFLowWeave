<script setup lang="ts">
import { computed, ref } from 'vue'
import type { JsonObject } from '@/shared/types'
import ParameterField from '@/shared/schema/ParameterField.vue'

const models = defineModel<Record<string, JsonObject>>({ required: true })
const props = defineProps<{ candidates: string[]; testing?: boolean; testDisabled?: boolean }>()
const emit = defineEmits<{ test: [] }>()
const name = ref('')
const addError = ref('')
const error = computed(
  () => addError.value || (name.value ? '请添加正在填写的模型，或清空模型名称' : ''),
)
const expanded = ref<string[]>([])
const hasModel = (candidate: string) =>
  Object.prototype.hasOwnProperty.call(models.value, candidate)
const candidates = computed(() => props.candidates.filter((candidate) => !hasModel(candidate)))
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
  const selected = name.value.trim()
  if (!selected) {
    addError.value = '请输入或选择模型名称'
    return
  }
  if (hasModel(selected)) {
    addError.value = '此渠道已添加该模型'
    return
  }
  models.value = { ...models.value, [selected]: {} }
  name.value = ''
  addError.value = ''
}
function suggestModels(query: string, callback: (items: { value: string }[]) => void) {
  callback(
    candidates.value
      .filter((candidate) => candidate.toLowerCase().includes(query.toLowerCase()))
      .map((value) => ({ value })),
  )
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
      <el-button
        v-if="!Object.keys(models).length"
        :loading="testing"
        :disabled="testDisabled"
        @click="emit('test')"
      >
        测试连接
      </el-button>
    </div>
    <p class="muted text-sm mb-3">在此添加模型，保存后即可在工作流的并行 AI 分析中选择。</p>
    <el-form-item prop="models" :rules="{ validator: validate }">
      <div class="flex gap-2 w-full min-w-0">
        <el-autocomplete
          v-model="name"
          :fetch-suggestions="suggestModels"
          clearable
          aria-label="模型名称"
          placeholder="输入模型名称，或选择检查发现的模型"
          class="min-w-0 flex-1"
          @update:model-value="addError = ''"
          @keydown.enter.prevent
        />
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
          <el-button :loading="testing" :disabled="testDisabled" @click="emit('test')">
            测试连接
          </el-button>
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
