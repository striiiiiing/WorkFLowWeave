<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { agentsApi, type AgentModel } from '@/api/agents'
import { runsApi } from '@/api/runs'
import type { SessionRecord } from '@/types'
import { useAsyncTask } from '@/composables/useAsyncTask'
const props = defineProps<{ workflowId?: string; workflowSessionId?: string }>()
const router = useRouter()
const action = useAsyncTask()
const visible = ref(false)
const model = ref('')
const models = ref<AgentModel[]>([])
const source = ref<SessionRecord>()
async function open() {
  visible.value = true
  source.value = undefined
  await action.run(async () => {
    models.value = await agentsApi.models()
    if (props.workflowSessionId) source.value = await runsApi.get(props.workflowSessionId)
    else {
      const records = await runsApi.list({ workflow_id: props.workflowId, limit: 1000 })
      source.value = records
        .filter((item) => ['completed', 'partial'].includes(item.status))
        .sort((a, b) =>
          (b.finished_at ?? b.updated_at).localeCompare(a.finished_at ?? a.updated_at),
        )[0]
    }
    if (!source.value) throw new Error('Workflow 没有可继续的最终结果')
  })
}
async function create() {
  if (!source.value) return
  const session = await action.run(() =>
    agentsApi.create({
      workflow_session_id: source.value!.session_id,
      ...(model.value ? { model: model.value } : {}),
    }),
  )
  if (session) {
    visible.value = false
    await router.push(`/agents/${encodeURIComponent(session.session_id)}`)
  }
}
</script>
<template>
  <el-button @click="open">{{ workflowSessionId ? '继续讨论' : '从最新结果继续' }}</el-button>
  <el-dialog v-model="visible" title="从 Workflow 结果创建 Agent 会话" width="min(90vw, 580px)">
    <el-alert
      v-if="action.error.value"
      :title="action.error.value"
      type="error"
      :closable="false"
    />
    <p v-if="source">
      来源 {{ source.workflow_id }} / {{ source.session_id }}
      <br />
      结果时间 {{ source.finished_at ?? source.updated_at }}
    </p>
    <p>创建后固定此来源结果，后续 Workflow 运行不会替换当前上下文。</p>
    <el-select v-model="model" placeholder="选择模型（可选）" clearable aria-label="续接模型">
      <el-option
        v-for="item in models"
        :key="item.reference"
        :value="item.reference"
        :label="`${item.provider} / ${item.reference}`"
      />
    </el-select>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :disabled="!source" :loading="action.pending.value" @click="create">
        创建并继续
      </el-button>
    </template>
  </el-dialog>
</template>
