<script setup lang="ts">
import type { WorkflowDefinition, AIConfig } from '@/types'
import { createFanIn } from '@/domain/workflow'
import SectionCard from '@/components/common/SectionCard.vue'
import AIModelSelect from './AIModelSelect.vue'
const model = defineModel<WorkflowDefinition>({ required: true })
defineProps<{ configs: AIConfig[] }>()
function toggle(enabled: boolean | string | number) {
  model.value.fan_in = enabled ? createFanIn() : null
}
</script>
<template>
  <SectionCard title="3. 汇聚汇总" description="按指定顺序拼接，可选 AI 汇总">
    <template #actions>
      <el-switch :model-value="model.fan_in !== null" aria-label="启用汇聚" @change="toggle" />
    </template>
    <template v-if="model.fan_in">
      <el-form-item label="汇聚顺序（留空使用默认顺序）">
        <el-select v-model="model.fan_in.order" multiple>
          <el-option value="$input" label="共享输入" />
          <el-option
            v-for="task in model.analyses"
            :key="task.id"
            :value="task.id"
            :label="task.id"
          />
        </el-select>
      </el-form-item>
      <AIModelSelect
        v-model:ai="model.fan_in.ai"
        v-model:model="model.fan_in.model"
        :configs="configs"
        optional
      />
      <el-form-item v-if="model.fan_in.ai" label="汇总提示词">
        <el-input v-model="model.fan_in.prompt" type="textarea" :rows="3" />
      </el-form-item>
      <el-form-item label="分隔符">
        <el-input v-model="model.fan_in.separator" type="textarea" :rows="2" />
      </el-form-item>
      <el-form-item label="标记不完整结果">
        <el-switch v-model="model.fan_in.mark_incomplete" />
      </el-form-item>
    </template>
    <p v-else class="muted">未启用汇聚，直接使用各分析任务的结果。</p>
  </SectionCard>
</template>
