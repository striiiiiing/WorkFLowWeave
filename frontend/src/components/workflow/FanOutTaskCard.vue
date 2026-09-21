<script setup lang="ts">
import type { WorkflowDefinition, AIConfig } from '@/types'
import { idRule } from '@/domain/forms'
import SectionCard from '@/components/common/SectionCard.vue'
import AIModelSelect from './AIModelSelect.vue'
const model = defineModel<WorkflowDefinition>({ required: true })
const props = defineProps<{
  configs: AIConfig[]
  advanced?: boolean
  modelsPending?: boolean
}>()
const emit = defineEmits<{ refreshModels: [] }>()
function add() {
  let index = model.value.analyses.length + 1
  while (model.value.analyses.some((item) => item.id === `task_${index}`)) index++
  model.value.analyses.push({ id: `task_${index}`, ai: '', model: '', prompt: '{input}' })
}
function rename(index: number, id: string) {
  const previous = model.value.analyses[index].id
  model.value.analyses[index].id = id
  if (model.value.fan_in) {
    model.value.fan_in.order = model.value.fan_in.order.map((value) =>
      value === previous ? id : value,
    )
  }
}
function remove(index: number) {
  const task = model.value.analyses[index]
  model.value.analyses.splice(index, 1)
  if (model.value.fan_in)
    model.value.fan_in.order = model.value.fan_in.order.filter((id) => id !== task.id)
}
</script>
<template>
  <SectionCard title="2. 并行 AI 分析" description="各任务使用同一份共享输入">
    <template #actions>
      <el-button
        size="small"
        :loading="props.modelsPending"
        :disabled="props.modelsPending"
        @click="emit('refreshModels')"
      >
        刷新模型列表
      </el-button>
      <el-button size="small" @click="add">添加任务</el-button>
    </template>
    <el-form-item
      prop="analyses"
      :rules="{ type: 'array', required: true, min: 1, message: '至少添加一个分析任务' }"
    >
      <span v-if="!model.analyses.length" class="muted">尚未添加分析任务</span>
    </el-form-item>
    <div
      v-for="(task, index) in model.analyses"
      :key="index"
      class="p-4 border border-slate-200 dark:border-slate-700 rounded-lg mb-4"
    >
      <div class="flex items-center justify-between mb-3">
        <h3 class="font-semibold">分析任务 {{ index + 1 }}</h3>
        <el-button type="danger" text @click="remove(index)">移除</el-button>
      </div>
      <el-form-item label="任务 ID" :prop="`analyses.${index}.id`" :rules="idRule">
        <el-input :model-value="task.id" @update:model-value="rename(index, $event)" />
      </el-form-item>
      <AIModelSelect
        :ai="task.ai"
        :model="task.model"
        :configs="configs"
        :ai-prop="`analyses.${index}.ai`"
        :model-prop="`analyses.${index}.model`"
        @update:ai="task.ai = $event ?? ''"
        @update:model="task.model = $event ?? ''"
      />
      <el-form-item label="提示词">
        <el-input
          v-model="task.prompt"
          type="textarea"
          :rows="3"
          placeholder="使用 {input} 引用共享输入"
        />
      </el-form-item>
    </div>
    <div v-if="advanced" class="form-grid">
      <el-form-item label="分析并发">
        <el-input-number v-model="model.analysis_concurrency" :min="1" :precision="0" />
      </el-form-item>
      <el-form-item label="分析失败时">
        <el-select v-model="model.analysis_failure">
          <el-option value="continue" label="继续其他任务" />
          <el-option value="stop" label="停止" />
        </el-select>
      </el-form-item>
    </div>
  </SectionCard>
</template>
