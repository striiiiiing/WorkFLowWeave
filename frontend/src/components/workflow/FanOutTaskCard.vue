<template>
  <!-- [Design Decision DEC-LAYOUT-01] 垂直流式阶梯编排卡片：Fan-Out 多任务并行分析阶段 -->
  <Card
    title="阶段 2：并行 AI 分析任务 (Fan-Out Analysis)"
    subtitle="将同一份编排后的共享输入分发给多个分析任务，分别指定提示词与模型"
    icon="bot"
  >
    <div class="space-y-4">
      <!-- 策略选项 -->
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 p-3 bg-slate-50 dark:bg-slate-900/50 rounded-lg border border-slate-200/60 dark:border-slate-700/60">
        <div>
          <label class="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
            单个分支失败策略 (analysis_failure)
          </label>
          <select
            v-model="workflow.analysis_failure"
            class="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 min-h-[44px]"
          >
            <option value="stop">stop (分支失败时阻止后续汇聚与发送)</option>
            <option value="continue">continue (允许使用成功分支的结果)</option>
          </select>
        </div>

        <div class="flex items-center">
          <Switch
            v-model="sendPartialModel"
            label="允许发送部分成功的分支结果 (send_partial)"
          />
        </div>
      </div>

      <!-- 分析任务卡片列表 -->
      <div class="space-y-3">
        <div class="flex items-center justify-between">
          <span class="text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider">
            分析任务列表 ({{ workflow.analysis_tasks.length }})
          </span>
          <Button size="sm" variant="secondary" icon="plus" @click="addTask">
            添加分析分支
          </Button>
        </div>

        <div v-if="workflow.analysis_tasks.length === 0" class="p-6 text-center border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-lg text-slate-400 text-sm">
          暂无分析任务，请点击上方按钮添加
        </div>

        <div
          v-for="(task, index) in workflow.analysis_tasks"
          :key="task.task_id"
          class="p-4 bg-white dark:bg-slate-800/90 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm space-y-3"
        >
          <div class="flex items-center justify-between border-b border-slate-100 dark:border-slate-700 pb-2">
            <div class="flex items-center gap-2">
              <span class="w-5 h-5 rounded-full bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 text-xs font-bold flex items-center justify-center">
                {{ index + 1 }}
              </span>
              <span class="text-xs font-medium text-slate-500">分支标识:</span>
              <span class="font-mono text-xs font-bold text-slate-800 dark:text-slate-200">{{ task.task_id }}</span>
            </div>
            <button
              type="button"
              class="p-1.5 text-red-500 hover:text-red-700 min-h-[36px] min-w-[36px] flex items-center justify-center"
              title="删除分支"
              @click="removeTask(index)"
            >
              <AppIcon name="trash" size="sm" />
            </button>
          </div>

          <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Input
              v-model="task.task_name"
              label="任务名称/说明"
              placeholder="如：提取异常指标"
            />

            <div>
              <label class="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                AI 配置引用 <span class="text-red-500">*</span>
              </label>
              <select
                v-model="task.ai"
                class="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 min-h-[44px]"
                @change="onAiChange(task)"
              >
                <option value="" disabled>请选择 AI 配置</option>
                <option v-for="ai in availableAIs" :key="ai.id" :value="ai.id">
                  {{ ai.id }} ({{ ai.provider }})
                </option>
              </select>
            </div>

            <div>
              <label class="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                模型名 (model) <span class="text-red-500">*</span>
              </label>
              <input
                v-model="task.model"
                type="text"
                class="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 font-mono text-xs min-h-[44px]"
                placeholder="如：gpt-4o / deepseek-chat"
              />
            </div>
          </div>

          <!-- 提示词 Prompt -->
          <div>
            <Input
              v-model="task.prompt"
              label="分析提示词 (Prompt)"
              as="textarea"
              :rows="3"
              placeholder="请输入该分支所使用的分析指令模板..."
              hint="同一份编排好的完整共享输入将自动拼接到提示词之后传入模型"
            />
          </div>
        </div>
      </div>
    </div>
  </Card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Card from '@/components/common/Card.vue'
import Button from '@/components/common/Button.vue'
import Input from '@/components/common/Input.vue'
import Switch from '@/components/common/Switch.vue'
import AppIcon from '@/components/icons/AppIcon.vue'
import type { WorkflowDefinition, AIConfig, AnalysisTask } from '@/types'

const props = defineProps<{
  workflow: WorkflowDefinition
  availableAIs: AIConfig[]
}>()

const sendPartialModel = computed({
  get: () => !!props.workflow.send_partial,
  set: (val) => {
    props.workflow.send_partial = val
  }
})

function addTask() {
  const newId = `task_${props.workflow.analysis_tasks.length + 1}`
  const defaultAi = props.availableAIs[0]?.id || ''
  const defaultModel = props.availableAIs[0]?.models ? Object.keys(props.availableAIs[0].models)[0] || '' : ''

  props.workflow.analysis_tasks.push({
    task_id: newId,
    task_name: `分析分支 ${props.workflow.analysis_tasks.length + 1}`,
    ai: defaultAi,
    model: defaultModel,
    prompt: '请分析以上采集到的日志或数据，提取关键结论。',
  })
}

function removeTask(index: number) {
  props.workflow.analysis_tasks.splice(index, 1)
}

function onAiChange(task: AnalysisTask) {
  const ai = props.availableAIs.find((a) => a.id === task.ai)
  if (ai && ai.models) {
    const firstModel = Object.keys(ai.models)[0]
    if (firstModel) {
      task.model = firstModel
    }
  }
}
</script>
