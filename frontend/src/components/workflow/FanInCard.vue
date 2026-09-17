<template>
  <!-- [Design Decision DEC-LAYOUT-01] 垂直流式阶梯编排卡片：Fan-In 汇聚汇总阶段 -->
  <Card
    title="阶段 3：汇聚汇总 (Fan-In Aggregate)"
    subtitle="对多个并行分析任务的分支结果进行再次拼接或 AI 综合总结 (可选)"
    icon="workflow"
  >
    <div class="space-y-4">
      <div class="flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-900/50 rounded-lg border border-slate-200/60 dark:border-slate-700/60">
        <div>
          <span class="text-sm font-semibold text-slate-800 dark:text-slate-200">启用汇聚阶段 (fan-in)</span>
          <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            关闭时各成功分析分支将分别作为独立输出；开启时将汇总为一份最终报告
          </p>
        </div>
        <Switch v-model="fanInEnabled" />
      </div>

      <div v-if="fanInEnabled" class="p-4 bg-white dark:bg-slate-800/90 rounded-lg border border-slate-200 dark:border-slate-700 space-y-3">
        <p class="text-xs font-semibold text-slate-700 dark:text-slate-300">
          汇总模式配置 (若不指定 AI 与模型，系统将按顺序执行纯文本结构化拼接)
        </p>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1.5">
              AI 模型配置 (留空表示纯拼接)
            </label>
            <select
              v-model="selectedAi"
              class="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 min-h-[44px]"
              @change="onAiChange"
            >
              <option :value="null">不使用 AI (仅纯文本拼接)</option>
              <option v-for="ai in availableAIs" :key="ai.id" :value="ai.id">
                {{ ai.id }} ({{ ai.provider }})
              </option>
            </select>
          </div>

          <div v-if="selectedAi">
            <label class="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1.5">
              模型名 (model)
            </label>
            <input
              v-model="selectedModel"
              type="text"
              class="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 font-mono text-xs min-h-[44px]"
              placeholder="如：gpt-4o"
            />
          </div>
        </div>

        <div v-if="selectedAi">
          <Input
            v-model="promptModel"
            label="汇总综合提示词 (Prompt)"
            as="textarea"
            :rows="3"
            placeholder="请综合以上各分支分析结果，给出最终概要结论..."
          />
        </div>
      </div>
    </div>
  </Card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Card from '@/components/common/Card.vue'
import Switch from '@/components/common/Switch.vue'
import Input from '@/components/common/Input.vue'
import type { WorkflowDefinition, AIConfig } from '@/types'

const props = defineProps<{
  workflow: WorkflowDefinition
  availableAIs: AIConfig[]
}>()

const fanInEnabled = computed({
  get: () => !!props.workflow.fan_in?.enabled,
  set: (val) => {
    if (!props.workflow.fan_in) {
      props.workflow.fan_in = { enabled: val }
    } else {
      props.workflow.fan_in.enabled = val
    }
  }
})

const selectedAi = computed({
  get: () => props.workflow.fan_in?.ai || null,
  set: (val) => {
    if (!props.workflow.fan_in) props.workflow.fan_in = { enabled: true }
    props.workflow.fan_in.ai = val
    if (!val) {
      props.workflow.fan_in.model = null
    }
  }
})

const selectedModel = computed({
  get: () => props.workflow.fan_in?.model || '',
  set: (val) => {
    if (!props.workflow.fan_in) props.workflow.fan_in = { enabled: true }
    props.workflow.fan_in.model = val
  }
})

const promptModel = computed({
  get: () => props.workflow.fan_in?.prompt || '',
  set: (val) => {
    if (!props.workflow.fan_in) props.workflow.fan_in = { enabled: true }
    props.workflow.fan_in.prompt = val
  }
})

function onAiChange() {
  if (selectedAi.value) {
    const ai = props.availableAIs.find((a) => a.id === selectedAi.value)
    if (ai && ai.models) {
      const first = Object.keys(ai.models)[0]
      if (first) selectedModel.value = first
    }
  }
}
</script>
