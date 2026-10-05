<script setup lang="ts">
import type { AgentTaskConfig } from '../model/types'
import { changeAgentMode } from '../model/agentTask'
const props = defineProps<{
  task: AgentTaskConfig & { user_prompt: string }
  advanced?: boolean
  tools?: readonly { name: string; enabled: boolean }[]
}>()
const emit = defineEmits<{ update: [value: AgentTaskConfig & { user_prompt?: string }] }>()
</script>
<template>
  <el-form-item>
    <el-checkbox
      :model-value="task.agent_mode ?? false"
      @update:model-value="emit('update', changeAgentMode(props.task, Boolean($event)))"
    >
      使用 Agent
    </el-checkbox>
  </el-form-item>
  <template v-if="advanced && task.agent_mode">
    <el-form-item label="工具">
      <el-checkbox
        :model-value="task.agent_tools == null"
        @update:model-value="emit('update', { agent_tools: $event ? null : [] })"
      >
        继承全部已启用工具
      </el-checkbox>
      <el-select
        v-if="task.agent_tools != null"
        :model-value="task.agent_tools"
        multiple
        clearable
        filterable
        placeholder="不选择则不使用工具"
        aria-label="当前任务的工具"
        @update:model-value="emit('update', { agent_tools: $event })"
      >
        <el-option
          v-for="tool in tools"
          :key="tool.name"
          :value="tool.name"
          :label="tool.name"
          :disabled="!tool.enabled"
        />
      </el-select>
    </el-form-item>
  </template>
</template>
