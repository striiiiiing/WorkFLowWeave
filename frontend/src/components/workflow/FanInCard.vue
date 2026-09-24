<script setup lang="ts">
import { ref, toRaw, watch } from 'vue'
import type { WorkflowDefinition, AIConfig, FanInConfig } from '@/types'
import { createFanIn } from '@/domain/workflow'
import SectionCard from '@/shared/ui/SectionCard.vue'
import AIModelSelect from './AIModelSelect.vue'
const model = defineModel<WorkflowDefinition>({ required: true })
defineProps<{ configs: AIConfig[]; advanced?: boolean }>()
const disabledDraft = ref<FanInConfig | null>(null)
watch(
  () => model.value.analyses.map((task) => ({ task, id: task.id })),
  (current, previous) => {
    if (!disabledDraft.value) return
    const renamed = new Map(
      previous.map((entry) => [entry.id, current.find((item) => item.task === entry.task)?.id]),
    )
    disabledDraft.value.order = disabledDraft.value.order.flatMap((id) => {
      if (id === '$input') return [id]
      const next = renamed.get(id)
      return next ? [next] : []
    })
  },
)
function toggle(enabled: boolean | string | number) {
  if (enabled) {
    model.value.fan_in = structuredClone(toRaw(disabledDraft.value ?? createFanIn()))
    disabledDraft.value = null
    return
  }
  disabledDraft.value = model.value.fan_in ? structuredClone(toRaw(model.value.fan_in)) : null
  model.value.fan_in = null
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
        ai-prop="fan_in.ai"
        model-prop="fan_in.model"
        optional
      />
      <el-form-item v-if="model.fan_in.ai" label="汇总提示词">
        <el-input v-model="model.fan_in.prompt" type="textarea" :rows="3" />
      </el-form-item>
      <el-form-item v-if="advanced" label="分隔符">
        <el-input v-model="model.fan_in.separator" type="textarea" :rows="2" />
      </el-form-item>
      <el-form-item v-if="advanced" label="标记不完整结果">
        <el-switch v-model="model.fan_in.mark_incomplete" />
      </el-form-item>
    </template>
    <p v-else class="muted">未启用汇聚，直接使用各分析任务的结果。</p>
  </SectionCard>
</template>
