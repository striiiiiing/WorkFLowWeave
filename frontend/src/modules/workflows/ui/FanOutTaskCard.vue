<script setup lang="ts">
import type { AIConfig } from '@/modules/resources/public'
import type { AnalysisTask } from '../model/types'
import type { WorkflowEditorController } from '../composables/useWorkflowEditor'
import AIModelSelect from './AIModelSelect.vue'
import AgentTaskOptions from './AgentTaskOptions.vue'
import PromptOverrides from './PromptOverrides.vue'
import SectionCard from '@/shared/ui/SectionCard.vue'
const props = defineProps<{
  editor: WorkflowEditorController
  configs: readonly AIConfig[]
  advanced?: boolean
  tools?: readonly { name: string; enabled: boolean }[]
}>()
const draft = () => props.editor.draft.value!
function taskId(index: number, task: AnalysisTask) {
  return props.editor.analysisDraftIds.value[index] ?? task.id
}
</script>
<template>
  <SectionCard title="2. 并行 AI 分析" description="各任务使用同一份共享输入">
    <template #actions>
      <el-button size="small" @click="editor.addTask">添加任务</el-button>
    </template>
    <el-form-item
      prop="analyses"
      :rules="{ type: 'array', required: true, min: 1, message: '至少添加一个分析任务' }"
    >
      <span v-if="!draft().analyses.length" class="muted">尚未添加分析任务</span>
    </el-form-item>
    <div
      v-for="(task, index) in draft().analyses"
      :key="`${task.id}-${index}`"
      class="p-4 border rounded-lg mb-4"
    >
      <div class="flex items-center justify-between mb-3">
        <h3 class="font-semibold">分析任务 {{ index + 1 }}</h3>
        <el-button type="danger" text @click="editor.deleteTask(index)">移除</el-button>
      </div>
      <el-form-item
        label="任务 ID"
        :prop="`analyses.${index}.id`"
        :error="editor.taskIdError(index) || undefined"
      >
        <el-input
          :model-value="taskId(index, task)"
          @update:model-value="editor.updateTaskId(index, $event)"
        />
      </el-form-item>
      <AIModelSelect
        :ai="task.ai || null"
        :model="task.model || null"
        :configs="configs"
        :ai-prop="`analyses.${index}.ai`"
        :model-prop="`analyses.${index}.model`"
        @selection="(ai, model) => editor.updateTask(index, { ai: ai ?? '', model: model ?? '' })"
      />
      <AgentTaskOptions
        :task="task"
        :advanced="advanced"
        :tools="tools"
        @update="editor.updateTask(index, $event)"
      />
      <el-form-item label="提示词">
        <el-input
          :model-value="task.user_prompt"
          type="textarea"
          :rows="3"
          @update:model-value="editor.updateTask(index, { user_prompt: $event })"
        />
      </el-form-item>
      <PromptOverrides
        v-if="advanced"
        :value="task"
        :shared-system-prompt="draft().system_prompt"
        :shared-input-prompt="draft().input_prompt"
        @update="editor.updateTask(index, $event)"
      />
    </div>
    <div v-if="advanced" class="form-grid">
      <el-form-item label="分析并发">
        <el-input-number
          :model-value="draft().analysis_concurrency"
          :min="1"
          :precision="0"
          @update:model-value="editor.update({ analysis_concurrency: $event ?? 1 })"
        />
      </el-form-item>
      <el-form-item label="分析失败时">
        <el-select
          :model-value="draft().analysis_failure"
          @update:model-value="editor.update({ analysis_failure: $event })"
        >
          <el-option value="continue" label="继续其他任务" />
          <el-option value="stop" label="停止" />
        </el-select>
      </el-form-item>
    </div>
  </SectionCard>
</template>
