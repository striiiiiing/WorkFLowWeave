<script setup lang="ts">
import type { AnalysisTask } from '../model/types'

const props = defineProps<{
  value: Pick<AnalysisTask, 'system_prompt' | 'input_prompt' | 'user_prompt'>
  sharedSystemPrompt: string
  sharedInputPrompt: string
}>()
const emit = defineEmits<{
  update: [changes: Partial<Pick<AnalysisTask, 'system_prompt' | 'input_prompt' | 'user_prompt'>>]
}>()

function switchSystem(mode: string | number | boolean | undefined) {
  if (mode !== 'shared' && mode !== 'override') throw new Error('未知系统提示词模式')
  emit('update', { system_prompt: mode === 'shared' ? null : props.sharedSystemPrompt })
}
function switchInput(mode: string | number | boolean | undefined) {
  if (mode !== 'shared' && mode !== 'override') throw new Error('未知输入模板模式')
  emit('update', { input_prompt: mode === 'shared' ? null : props.sharedInputPrompt })
}
</script>

<template>
  <el-form-item label="系统提示词">
    <div class="prompt-control">
      <el-radio-group
        :model-value="value.system_prompt === null ? 'shared' : 'override'"
        @update:model-value="switchSystem"
      >
        <el-radio-button value="shared" label="使用共享值" />
        <el-radio-button value="override" label="单独设置" />
      </el-radio-group>
      <el-input
        v-if="value.system_prompt !== null"
        :model-value="value.system_prompt"
        type="textarea"
        :rows="3"
        aria-label="独立系统提示词"
        @update:model-value="emit('update', { system_prompt: $event })"
      />
    </div>
  </el-form-item>
  <el-form-item label="输入模板">
    <div class="prompt-control">
      <el-radio-group
        :model-value="value.input_prompt === null ? 'shared' : 'override'"
        @update:model-value="switchInput"
      >
        <el-radio-button value="shared" label="使用共享值" />
        <el-radio-button value="override" label="单独设置" />
      </el-radio-group>
      <el-input
        v-if="value.input_prompt !== null"
        :model-value="value.input_prompt"
        type="textarea"
        :rows="3"
        aria-label="独立输入模板"
        @update:model-value="emit('update', { input_prompt: $event })"
      />
    </div>
  </el-form-item>
  <el-form-item label="差异指令">
    <el-input
      :model-value="value.user_prompt"
      type="textarea"
      :rows="3"
      @update:model-value="emit('update', { user_prompt: $event })"
    />
  </el-form-item>
</template>

<style scoped>
.prompt-control {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  min-width: 0;
}
</style>
