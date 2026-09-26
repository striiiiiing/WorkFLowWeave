<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { isTaskSuccess, useAsyncTask } from '@/shared/async/useAsyncTask'
import { useAgentsApi, readDefaultAgentModel, type AgentModel } from '@/modules/agents/public'
import type { SessionRecord } from '@/modules/runs/public'

const props = defineProps<{ session: SessionRecord }>()
const router = useRouter()
const api = useAgentsApi()
const action = useAsyncTask()
const visible = ref(false)
const models = ref<AgentModel[]>([])
const model = ref('')
const preferredModel = ref('')
const canContinue = computed(() => ['completed', 'partial'].includes(props.session.status))
const modelPrompt = computed(() => {
  if (!preferredModel.value) return '请选择用于续接讨论的模型。'
  if (!models.value.some((item) => item.reference === preferredModel.value))
    return `默认模型“${preferredModel.value}”不在当前目录中，请选择可用模型。`
  return ''
})

async function open() {
  model.value = ''
  preferredModel.value = ''
  const result = await action.run(async () => {
    const available = await api.models()
    const preferred = readDefaultAgentModel()
    models.value = available
    preferredModel.value = preferred
    model.value = available.some((item) => item.reference === preferred) ? preferred : ''
  })
  if (isTaskSuccess(result) && model.value) await create()
  else visible.value = true
}

async function create() {
  if (!canContinue.value || !models.value.some((item) => item.reference === model.value)) return
  const result = await action.run(() =>
    api.create({ workflow_session_id: props.session.session_id, model: model.value }),
  )
  if (!isTaskSuccess(result)) {
    visible.value = true
    return
  }
  visible.value = false
  await router.push(`/agents/${encodeURIComponent(result.value.session_id)}`)
}
</script>

<template>
  <el-button v-if="canContinue" :loading="action.pending.value" @click="open">继续讨论</el-button>
  <el-dialog v-model="visible" title="从 Workflow 结果创建 Agent 会话" width="min(90vw, 580px)">
    <el-alert
      v-if="action.error.value"
      :title="action.error.value"
      type="error"
      :closable="false"
    />
    <template v-else>
      <p>来源 {{ session.workflow_id }} / {{ session.session_id }}</p>
      <p class="mb-3">本次运行记录会固定为新会话的上下文。</p>
      <el-select v-model="model" aria-label="续接模型" placeholder="选择模型" class="w-full">
        <el-option
          v-for="item in models"
          :key="item.reference"
          :label="`${item.ai} / ${item.model}`"
          :value="item.reference"
        />
      </el-select>
      <p v-if="modelPrompt" class="mt-2 text-sm" role="status">{{ modelPrompt }}</p>
    </template>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button :loading="action.pending.value" @click="open">重新加载模型</el-button>
      <el-button
        type="primary"
        :loading="action.pending.value"
        :disabled="!models.some((item) => item.reference === model)"
        @click="create"
      >
        创建并继续
      </el-button>
    </template>
  </el-dialog>
</template>
