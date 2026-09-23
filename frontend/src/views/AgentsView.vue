<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  agentsApi,
  type AgentEvent,
  type AgentSession,
  type ContextBudget,
  type TurnAccepted,
} from '@/api/agents'
import { useQuery } from '@/composables/useQuery'
import { useAsyncTask } from '@/composables/useAsyncTask'
import { useAgentStream } from '@/composables/useAgentStream'
import PageHeader from '@/components/common/PageHeader.vue'
import AgentBranchTree from '@/components/agent/AgentBranchTree.vue'
import AgentTranscript from '@/components/agent/AgentTranscript.vue'
import AgentFileDrawer from '@/components/agent/AgentFileDrawer.vue'
import AgentSettings from '@/components/agent/AgentSettings.vue'
import AgentContinueButton from '@/components/agent/AgentContinueButton.vue'
import type { SessionRecord } from '@/types'
import { ApiError } from '@/api/client'
const route = useRoute()
const router = useRouter()
const sessions = useQuery((signal) => agentsApi.list(signal))
const settings = useQuery((signal) => agentsApi.config(signal))
const action = useAsyncTask()
const stopAction = useAsyncTask()
const selected = ref<AgentSession>()
const sessionQuery = useQuery(
  (signal) =>
    typeof route.params.sessionId === 'string'
      ? agentsApi.get(route.params.sessionId, signal)
      : Promise.resolve(undefined),
  [() => route.params.sessionId],
)
const draft = ref('')
const pendingInput = ref<{ session: string | null; text: string; requestId: string }>()
const sendUncertain = ref(false)
const model = ref('')
const showCreate = ref(false)
const showSessions = ref(false)
const showFiles = ref(false)
const showSettings = ref(false)
const showSource = ref(false)
const showWorkflows = ref(false)
const workflowHistory = ref<SessionRecord[]>([])
const filePath = ref('AGENTS.md')
const source = ref<Awaited<ReturnType<typeof agentsApi.source>>>()
const editEvent = ref<AgentEvent>()
const editText = ref('')
const running = computed(() => selected.value?.status === 'running')
const budget = computed(() => selected.value?.context_budget)
const stream = useAgentStream((event) => {
  if (!selected.value || selected.value.session_id !== event.session_id) return
  if (event.type === 'turn.started')
    selected.value = { ...selected.value, status: 'running', turn_id: event.turn_id }
  if (event.type === 'context.budget')
    selected.value = { ...selected.value, context_budget: event.data as unknown as ContextBudget }
  if (event.type === 'turn.resources')
    selected.value = {
      ...selected.value,
      active_resources: event.data as AgentSession['active_resources'],
    }
  if (
    ['turn.completed', 'turn.failed', 'turn.cancelled', 'turn.interrupted'].includes(event.type)
  ) {
    const error = event.data.error as AgentSession['continuation_error']
    selected.value = {
      ...selected.value,
      status: event.type.slice(5),
      ...(event.data.checkpoint_id ? { last_checkpoint_at: event.at } : {}),
      ...(error && ['checkpoint_missing', 'checkpoint_corrupt'].includes(error.code)
        ? { continuable: false, continuation_error: error }
        : {}),
    }
    void sessions.refresh()
  }
})
watch(sessionQuery.data, async (session) => {
  selected.value = session
  showFiles.value = false
  showSource.value = false
  if (session) {
    const latest = await stream.select(session.session_id)
    if (latest && route.params.sessionId === latest.session_id) selected.value = latest
  } else stream.clear()
})
async function select(session: AgentSession) {
  showSessions.value = false
  if (route.params.sessionId === session.session_id) {
    await sessionQuery.refresh()
    return
  }
  await router.push(`/agents/${encodeURIComponent(session.session_id)}`)
}
async function create() {
  const result = await action.run(() => agentsApi.create(model.value ? { model: model.value } : {}))
  if (!result) return
  showCreate.value = false
  await sessions.refresh()
  await select(result)
}
async function send() {
  if (!draft.value.trim()) return
  const text = draft.value
  const sessionId = selected.value?.session_id ?? null
  if (pendingInput.value?.text !== text || pendingInput.value.session !== sessionId) {
    pendingInput.value = { session: sessionId, text, requestId: crypto.randomUUID() }
  }
  const input = pendingInput.value
  const result = await action.run(async () => {
    try {
      return await agentsApi.command(input.session, text, input.requestId)
    } catch (cause) {
      sendUncertain.value = !(cause instanceof ApiError)
      throw cause
    }
  })
  if (!result) return
  pendingInput.value = undefined
  sendUncertain.value = false
  draft.value = ''
  if (result.kind === 'session') {
    await sessions.refresh()
    await select(result.result as AgentSession)
  } else if (result.kind === 'workflows') {
    workflowHistory.value = result.result as SessionRecord[]
    showWorkflows.value = true
  } else if (selected.value) {
    const turn = result.result as TurnAccepted
    if (selected.value.session_id !== turn.session_id) return
    if (turn.deduplicated) {
      await sessionQuery.refresh()
      return
    }
    selected.value = { ...selected.value, status: 'running', turn_id: turn.turn_id }
    stream.resume(turn.turn_id)
  }
}
function command(text: string) {
  draft.value = text
}
async function stop() {
  if (!selected.value) return
  const result = await stopAction.run(() => agentsApi.cancel(selected.value!.session_id))
  if (result && selected.value?.session_id === result.session_id) selected.value = result
}
async function compact() {
  if (!selected.value) return
  const result = await action.run(() => agentsApi.compact(selected.value!.session_id))
  if (result && selected.value?.session_id === result.session_id) {
    selected.value = { ...selected.value, status: 'running', turn_id: result.turn_id }
    stream.resume(result.turn_id)
  }
}
async function fork() {
  if (!selected.value) return
  const child = await action.run(() => agentsApi.fork(selected.value!.session_id))
  if (child) {
    await sessions.refresh()
    await select(child)
  }
}
function edit(event: AgentEvent) {
  editEvent.value = event
  editText.value = String(event.data.text ?? '')
}
async function confirmEdit() {
  const event = editEvent.value
  if (!event || !editText.value.trim()) return
  const child = await action.run(async () => {
    const branch = await agentsApi.fork(event.session_id, {
      message_id: String(event.data.message_id),
    })
    await agentsApi.send(branch.session_id, crypto.randomUUID(), editText.value)
    return branch
  })
  if (child) {
    editEvent.value = undefined
    await sessions.refresh()
    await select(child)
  }
}
function openFile(path: string) {
  filePath.value = path
  showFiles.value = true
}
async function openSource() {
  if (!selected.value) return
  const sessionId = selected.value.session_id
  const value = await action.run(() => agentsApi.source(sessionId))
  if (value && selected.value?.session_id === sessionId) {
    source.value = value
    showSource.value = true
  }
}
async function setModel(value: string) {
  if (!selected.value) return
  const result = await action.run(() => agentsApi.setModel(selected.value!.session_id, value))
  if (result && selected.value?.session_id === result.session_id) {
    selected.value = result
    await sessions.refresh()
  }
}
</script>
<template>
  <PageHeader title="Agent 会话" description="文件优先的多轮分析入口">
    <el-button class="mobile-sessions" @click="showSessions = true">会话与分支</el-button>
    <el-button type="primary" @click="showCreate = true">新会话</el-button>
  </PageHeader>
  <el-alert
    v-if="
      sessionQuery.error.value ||
      action.error.value ||
      stopAction.error.value ||
      sessions.error.value ||
      settings.error.value ||
      stream.error.value
    "
    :title="
      sessionQuery.error.value ||
      action.error.value ||
      stopAction.error.value ||
      sessions.error.value ||
      settings.error.value ||
      stream.error.value
    "
    type="error"
    :closable="false"
  />
  <div class="agent-layout">
    <aside class="session-sidebar">
      <AgentBranchTree
        :sessions="sessions.data.value ?? []"
        :selected="selected?.session_id"
        @select="select"
      />
    </aside>
    <main class="conversation">
      <template v-if="selected">
        <header class="agent-toolbar">
          <strong>{{ selected.session_id }}</strong>
          <span>
            分支 {{ selected.branch_id }} · {{ selected.status }} ·
            {{
              stream.state.value === 'reconnecting'
                ? '连接中断，正在续传'
                : stream.state.value === 'connected'
                  ? '已连接'
                  : '历史已同步'
            }}
          </span>
          <el-select
            :model-value="selected.model"
            placeholder="选择下轮模型"
            aria-label="Agent 模型"
            @change="setModel"
          >
            <el-option
              v-for="item in settings.data.value?.models"
              :key="item.reference"
              :value="item.reference"
              :label="`${item.provider} / ${item.reference}`"
            />
          </el-select>
          <small v-if="running">
            本轮模型 {{ selected.active_resources?.model ?? selected.model }} · 工具代次
            {{ selected.active_resources?.tools_generation ?? '未发布' }}；设置变更下一轮生效
          </small>
          <div class="agent-actions">
            <el-button text @click="openSource">来源</el-button>
            <el-button text @click="openFile('AGENTS.md')">文件</el-button>
            <el-button text @click="showSettings = true">设置与工具</el-button>
            <el-button text :disabled="running || !selected.last_checkpoint_at" @click="fork">
              创建分支
            </el-button>
            <el-button text :disabled="!selected.continuable" @click="compact">压缩</el-button>
            <el-button text :disabled="!running" :loading="stopAction.pending.value" @click="stop">
              停止
            </el-button>
          </div>
          <p v-if="budget" class="context-budget">
            上下文 {{ budget.total.toLocaleString() }} / {{ budget.window.toLocaleString() }} ·
            {{ budget.estimated ? '估算' : '实际值' }} · 输出预留 {{ budget.output }} · 消息预算
            {{ budget.window - budget.system - budget.tools - budget.output }} · 触发线
            <span v-if="budget.trigger !== undefined">
              {{ budget.trigger }} Tokens（{{
                Math.round((budget.trigger / budget.window) * 100)
              }}%）
            </span>
            <span v-else>历史未记录，下轮重新计算</span>
          </p>
          <p v-else class="context-budget">
            用户上下文预算 C={{
              settings.data.value?.config.context_window ?? '未知，需配置或模型声明'
            }}
            · 输出预留 R={{ settings.data.value?.config.output_tokens }} · 尚无请求用量
          </p>
          <small>
            沙箱：{{
              !settings.data.value?.sandbox.enabled
                ? '按服务进程权限运行'
                : settings.data.value.sandbox.available
                  ? '已开启（执行时验证隔离）'
                  : '隔离启动失败：bubblewrap 不可用'
            }}
          </small>
        </header>
        <div v-if="!selected.continuable">
          <el-alert
            :title="selected.continuation_error?.message ?? 'checkpoint 不可用，无法继续此会话'"
            type="error"
            :closable="false"
          />
          <el-button @click="openFile(selected.history_path)">读取原始事件文件</el-button>
        </div>
        <AgentTranscript
          :events="stream.events.value"
          :tools="settings.data.value?.tools"
          :session-id="selected.session_id"
          :running="running"
          @edit="edit"
          @file="openFile"
        />
      </template>
      <el-empty v-else description="选择或创建一个会话，也可使用 /new、/resume、/workflow" />
      <form class="agent-composer" @submit.prevent="send">
        <el-alert
          v-if="sendUncertain"
          title="发送结果未知。草稿和请求编号已保留；普通消息与 /append 可用同一编号重试，其他指令请先查看历史。"
          type="warning"
          :closable="false"
        />
        <el-input
          v-model="draft"
          type="textarea"
          :rows="3"
          aria-label="Agent 消息"
          placeholder="输入消息或 /append 追加内容；/workflow 查看历史"
          :disabled="selected?.continuable === false"
        />
        <div class="compose-actions">
          <el-button
            v-for="cmd in ['/new', '/resume ', '/workflow', '/append ', '/compact', '/fork']"
            :key="cmd"
            text
            size="small"
            @click="command(cmd)"
          >
            {{ cmd.trim() }}
          </el-button>
          <el-button
            type="primary"
            native-type="submit"
            :loading="action.pending.value"
            :disabled="!draft.trim() || selected?.continuable === false"
          >
            发送
          </el-button>
        </div>
        <small>
          优先级：停止 &gt; 指令 &gt; 普通对话。运行时使用 /append 追加；停止不撤销已完成的副作用。
        </small>
      </form>
    </main>
  </div>
  <el-drawer v-model="showSessions" title="会话与分支" size="min(90vw, 380px)">
    <AgentBranchTree
      :sessions="sessions.data.value ?? []"
      :selected="selected?.session_id"
      @select="select"
    />
  </el-drawer>
  <el-drawer v-model="showFiles" title="Agent 文件" size="min(95vw, 720px)" destroy-on-close>
    <AgentFileDrawer
      v-if="selected && showFiles"
      :session-id="selected.session_id"
      :initial-path="filePath"
    />
  </el-drawer>
  <el-drawer
    v-model="showSettings"
    title="Agent 设置与工具"
    size="min(95vw, 640px)"
    destroy-on-close
  >
    <AgentSettings v-if="showSettings" @changed="settings.refresh" />
  </el-drawer>
  <el-drawer v-model="showSource" title="只读 Workflow 来源" size="min(95vw, 640px)">
    <p>Workflow session：{{ source?.workflow_session_id ?? '无' }}</p>
    <p>绑定时间 {{ source?.created_at }}</p>
    <p>模型 {{ selected?.model }}</p>
    <pre>{{ JSON.stringify(source?.input, null, 2) }}</pre>
  </el-drawer>
  <el-drawer v-model="showWorkflows" title="Workflow 历史" size="min(95vw, 640px)">
    <p>使用 /workflow &lt;session_id&gt; 从指定最终结果创建会话。</p>
    <article v-for="record in workflowHistory" :key="record.session_id" class="workflow-history">
      <router-link :to="`/runs/${record.session_id}`">
        {{ record.workflow_id }} / {{ record.session_id }}
      </router-link>
      <p>{{ record.status }} · {{ record.finished_at ?? record.updated_at }}</p>
      <AgentContinueButton
        v-if="['completed', 'partial'].includes(record.status)"
        :workflow-session-id="record.session_id"
      />
    </article>
  </el-drawer>
  <el-dialog v-model="showCreate" title="创建 Agent 会话" width="min(90vw, 520px)">
    <el-select v-model="model" placeholder="选择模型（可选）" clearable aria-label="新会话模型">
      <el-option
        v-for="item in settings.data.value?.models"
        :key="item.reference"
        :value="item.reference"
        :label="`${item.provider} / ${item.reference}`"
      />
    </el-select>
    <template #footer>
      <el-button @click="showCreate = false">取消</el-button>
      <el-button type="primary" :loading="action.pending.value" @click="create">创建</el-button>
    </template>
  </el-dialog>
  <el-dialog
    :model-value="!!editEvent"
    title="编辑分支预览"
    width="min(90vw, 620px)"
    @close="editEvent = undefined"
  >
    <p>将从此用户消息之前创建分支，再发送下面的新内容；父分支和工具回执保留。</p>
    <el-input v-model="editText" type="textarea" :rows="6" aria-label="分支消息" />
    <template #footer>
      <el-button @click="editEvent = undefined">取消</el-button>
      <el-button type="primary" :loading="action.pending.value" @click="confirmEdit">
        确认创建分支并发送
      </el-button>
    </template>
  </el-dialog>
</template>
<style scoped>
.agent-layout {
  display: grid;
  grid-template-columns: minmax(180px, 250px) minmax(0, 1fr);
  gap: 16px;
}
.session-sidebar {
  max-height: calc(100vh - 170px);
  overflow-y: auto;
}
.conversation {
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  min-height: 65vh;
  max-height: calc(100vh - 150px);
}
.agent-toolbar {
  display: grid;
  gap: 6px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  overflow-wrap: anywhere;
}
.agent-toolbar .el-select {
  max-width: 360px;
}
.agent-actions,
.compose-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}
.context-budget,
small {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.agent-composer {
  display: grid;
  align-items: stretch;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid var(--border);
}
.workflow-history {
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
  overflow-wrap: anywhere;
}
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.mobile-sessions {
  display: none;
}
@media (max-width: 720px) {
  .agent-layout {
    display: block;
  }
  .session-sidebar {
    display: none;
  }
  .mobile-sessions {
    display: inline-flex;
  }
  .conversation {
    max-height: none;
    min-height: 60vh;
  }
  .agent-toolbar {
    padding: 10px;
  }
}
</style>
