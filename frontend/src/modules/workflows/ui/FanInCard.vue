<script setup lang="ts">
import type { AIConfig } from '@/modules/resources/public'
import type { WorkflowEditorController } from '../composables/useWorkflowEditor'
import AIModelSelect from './AIModelSelect.vue'
import SectionCard from '@/shared/ui/SectionCard.vue'
const props = defineProps<{
  editor: WorkflowEditorController
  configs: readonly AIConfig[]
  advanced?: boolean
}>()
const draft = () => props.editor.draft.value!
const fanIn = () => props.editor.draft.value!.fan_in!
</script>
<template>
  <SectionCard title="3. 汇聚汇总" description="按指定顺序拼接，可选 AI 汇总">
    <template #actions>
      <el-switch
        :model-value="draft().fan_in !== null"
        aria-label="启用汇聚"
        @update:model-value="editor.toggleFanIn(Boolean($event))"
      />
    </template>
    <template v-if="draft().fan_in">
      <el-form-item label="汇聚顺序（留空使用默认顺序）">
        <el-select
          :model-value="fanIn().order"
          multiple
          @update:model-value="editor.updateFanIn({ order: $event })"
        >
          <el-option value="$input" label="共享输入" />
          <el-option
            v-for="task in draft().analyses"
            :key="task.id"
            :value="task.id"
            :label="task.id"
          />
        </el-select>
      </el-form-item>
      <AIModelSelect
        :ai="fanIn().ai"
        :model="fanIn().model"
        :configs="configs"
        ai-prop="fan_in.ai"
        model-prop="fan_in.model"
        optional
        @update:ai="editor.updateFanIn({ ai: $event })"
        @update:model="editor.updateFanIn({ model: $event })"
      />
      <el-form-item v-if="fanIn().ai" label="汇总提示词">
        <el-input
          :model-value="fanIn().prompt"
          type="textarea"
          :rows="3"
          @update:model-value="editor.updateFanIn({ prompt: $event })"
        />
      </el-form-item>
      <el-form-item v-if="advanced" label="分隔符">
        <el-input
          :model-value="fanIn().separator"
          type="textarea"
          :rows="2"
          @update:model-value="editor.updateFanIn({ separator: $event })"
        />
      </el-form-item>
      <el-form-item v-if="advanced" label="标记不完整结果">
        <el-switch
          :model-value="fanIn().mark_incomplete"
          @update:model-value="editor.updateFanIn({ mark_incomplete: Boolean($event) })"
        />
      </el-form-item>
    </template>
    <p v-else class="muted">未启用汇聚，直接使用各分析任务的结果。</p>
  </SectionCard>
</template>
