<script setup lang="ts">
import { ArrowDown, ArrowUp } from 'lucide-vue-next'
import type { AIConfig } from '@/modules/resources/public'
import type { WorkflowEditorController } from '../composables/useWorkflowEditor'
import AIModelSelect from './AIModelSelect.vue'
import PromptOverrides from './PromptOverrides.vue'
import SectionCard from '@/shared/ui/SectionCard.vue'
const props = defineProps<{
  editor: WorkflowEditorController
  configs: readonly AIConfig[]
  advanced?: boolean
}>()
const draft = () => props.editor.draft.value!
const fanIn = () => props.editor.draft.value!.fan_in!
const orderedInputs = () =>
  fanIn().order.length ? fanIn().order : ['$input', ...draft().analyses.map((task) => task.id)]
function moveInput(index: number, delta: number) {
  const order = [...orderedInputs()]
  const target = index + delta
  if (target < 0 || target >= order.length) return
  ;[order[index], order[target]] = [order[target], order[index]]
  props.editor.updateFanIn({ order })
}
function selectModelSource(value: string) {
  props.editor.updateFanIn({
    reuse_from: value === '$none' ? null : value,
    ai: null,
    model: null,
  })
}
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
      <el-form-item label="汇聚顺序">
        <el-select
          :model-value="orderedInputs()"
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
      <div class="fan-in-order">
        <div v-for="(entry, index) in orderedInputs()" :key="entry" class="fan-in-order-row">
          <span>{{ entry === '$input' ? '共享输入' : entry }}</span>
          <div class="fan-in-order-actions">
            <el-button
              size="small"
              :disabled="index === 0"
              :aria-label="`上移 ${entry}`"
              :title="`上移 ${entry}`"
              @click="moveInput(index, -1)"
            >
              <ArrowUp :size="16" />
            </el-button>
            <el-button
              size="small"
              :disabled="index === orderedInputs().length - 1"
              :aria-label="`下移 ${entry}`"
              :title="`下移 ${entry}`"
              @click="moveInput(index, 1)"
            >
              <ArrowDown :size="16" />
            </el-button>
          </div>
        </div>
      </div>
      <el-form-item label="模型来源">
        <el-select
          :model-value="fanIn().reuse_from ?? '$none'"
          @update:model-value="selectModelSource"
        >
          <el-option value="$first" label="第一个分析任务" />
          <el-option
            v-for="task in draft().analyses"
            :key="task.id"
            :value="task.id"
            :label="task.id"
          />
          <el-option value="$none" label="独立选择或不使用 AI" />
        </el-select>
      </el-form-item>
      <AIModelSelect
        v-if="fanIn().reuse_from === null"
        :ai="fanIn().ai"
        :model="fanIn().model"
        :configs="configs"
        ai-prop="fan_in.ai"
        model-prop="fan_in.model"
        optional
        @selection="(ai, model) => editor.updateFanIn({ ai, model })"
      />
      <el-form-item label="提示词">
        <el-input
          :model-value="fanIn().user_prompt"
          type="textarea"
          :rows="3"
          @update:model-value="editor.updateFanIn({ user_prompt: $event })"
        />
      </el-form-item>
      <PromptOverrides
        v-if="advanced"
        :value="fanIn()"
        :shared-system-prompt="draft().system_prompt"
        :shared-input-prompt="draft().input_prompt"
        @update="editor.updateFanIn($event)"
      />
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
<style scoped>
.fan-in-order {
  margin: -8px 0 16px;
}
.fan-in-order-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 36px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.fan-in-order-actions {
  display: flex;
  gap: 4px;
}
.fan-in-order-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
</style>
