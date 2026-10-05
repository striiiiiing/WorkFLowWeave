<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import PageHeader from '@/shared/ui/PageHeader.vue'
import AppIcon from '@/shared/ui/icons/AppIcon.vue'
import {
  AgentSidebar,
  AgentHeader,
  AgentTranscript,
  AgentComposer,
  AgentBranchDrawer,
  AgentFileDrawer,
  AgentGlobalSettingsModal,
  AgentCreateDialog,
  AgentEditBranchDialog,
  useAgentsApi,
  useAgentSession,
  useAgentCommands,
  useAgentFiles,
  useAgentBranches,
  useAgentSettings,
  readDefaultAgentModel,
  readExpandReasoning,
  type SlashCommand,
  type AgentEvent,
  type AgentSession,
} from '@/modules/agents/public'
import { isTaskSuccess, useAsyncTask } from '@/shared/async/useAsyncTask'
import { useQuery } from '@/shared/async/useQuery'
import { useRunsApi } from '@/modules/runs/public'

const route = useRoute()
const router = useRouter()
const api = useAgentsApi()
const runsApi = useRunsApi()
const sessions = useQuery((signal) => api.list(signal))
const settings = useAgentSettings(api)
const session = useAgentSession(api)
const commands = useAgentCommands(api, { submit: session.submit, cancel: session.cancel })
const files = useAgentFiles(api)
const branches = useAgentBranches(api)
const action = useAsyncTask()
const createAction = useAsyncTask()
const selected = computed(() => session.session.value)
const running = computed(() => selected.value?.status === 'running')
const models = computed(() => settings.query.data.value?.models ?? [])
const showBranches = ref(false)
const showFiles = ref(false)
const showSettings = ref(false)
const showRename = ref(false)
const topicDraft = ref('')
const expandReasoning = ref(false)
function refreshDisplayPreferences() {
  try {
    expandReasoning.value = readExpandReasoning()
  } catch {
    ElMessage.error('无法读取浏览器思考过程显示设置')
  }
}
refreshDisplayPreferences()
const showCreate = ref(false)
const showSource = ref(false)
const showWorkflows = ref(false)
const filePath = ref('AGENTS.md')
const model = ref('')
const draft = commands.draft
const commandState = commands.current
watch(
  () => route.path,
  (path) => {
    if (!path.startsWith('/agents')) commands.clear()
  },
)
const source = ref<Awaited<ReturnType<typeof api.source>>>()
const workflowHistory = ref<Awaited<ReturnType<typeof runsApi.list>>>([])
const workflowAction = useAsyncTask()
const continueRecord = ref<(typeof workflowHistory.value)[number]>()
const continueModel = ref('')

const sessionId = computed(() =>
  typeof route.params.sessionId === 'string' ? route.params.sessionId : '',
)
watch(
  sessionId,
  (id) => {
    commands.select(id || null)
    showFiles.value = false
    showSource.value = false
    if (!id) {
      session.clear()
      return
    }
    void session.select(id).then((value) => {
      if (value) files.reset(id, filePath.value)
    })
  },
  { immediate: true },
)

function select(next: AgentSession) {
  showBranches.value = false
  void router.push(`/agents/${encodeURIComponent(next.session_id)}`)
}

async function openCreate() {
  try {
    model.value = readDefaultAgentModel()
  } catch {
    model.value = ''
    ElMessage.error('无法读取浏览器默认模型，请选择模型')
  }
  await settings.query.refresh()
  if (model.value && models.value.some((item) => item.reference === model.value)) {
    await create()
  } else showCreate.value = true
}

async function create() {
  const result = await createAction.run(() => api.create({ model: model.value }))
  if (!isTaskSuccess(result)) return
  showCreate.value = false
  await sessions.refresh()
  await router.push(`/agents/${encodeURIComponent((result.value as AgentSession).session_id)}`)
}

async function send() {
  if (!selected.value) return
  const originId = selected.value.session_id
  const input = commands.draft.value.trim()
  const modelForWorkflow = /^\/workflow\s+\S/.test(input) ? readDefaultAgentModel() : undefined
  const result = await commands.send(running.value, modelForWorkflow)
  if (!result) return
  if (result.kind === 'workflows') {
    workflowHistory.value = result.result as typeof workflowHistory.value
    showWorkflows.value = true
    return
  }
  if (route.params.sessionId !== originId) return
  if (result.kind === 'session') {
    await sessions.refresh()
    select(result.result as AgentSession)
  } else if (result.kind === 'turn') {
    const turn = result.result as { turn_id: string; status?: string; deduplicated?: boolean }
    if (turn.deduplicated) {
      await session.select(selected.value.session_id)
      return
    }
    if (turn.status !== 'queued') session.resume(turn.turn_id)
  }
}

async function stop() {
  const originId = selected.value?.session_id
  const result = await commands.stop()
  if (
    result &&
    originId === result.session_id &&
    selected.value?.session_id === result.session_id
  ) {
    await session.select(result.session_id)
    ElMessage.info(result.status === 'running' ? '停止请求已提交' : '会话执行已停止')
  }
}

async function fork(target: AgentSession | AgentEvent = selected.value as AgentSession) {
  if (!target) return
  const result = await action.run(() =>
    session.fork(
      target.session_id,
      'data' in target ? { turn_id: target.turn_id ?? undefined } : {},
    ),
  )
  if (isTaskSuccess(result)) {
    await sessions.refresh()
    select(result.value)
  }
}

async function compact() {
  if (!selected.value) return
  const id = selected.value.session_id
  const result = await action.run(() => session.compact(id))
  if (!isTaskSuccess(result) || selected.value?.session_id !== id) return
  if (result.value.status === 'queued') {
    ElMessage.info('压缩已排队，将在模型安全边界处理')
    return
  }
  session.resume(result.value.turn_id)
}

async function setModel(modelReference: string) {
  if (!selected.value) return
  const id = selected.value.session_id
  const result = await action.run(() => api.setModel(id, modelReference))
  if (!isTaskSuccess(result) || selected.value?.session_id !== id) return
  session.session.value = {
    ...selected.value,
    model: result.value.model,
    updated_at: result.value.updated_at,
  }
  await sessions.refresh()
}
function openRename() {
  topicDraft.value = selected.value?.title ?? ''
  showRename.value = true
}
async function renameTopic() {
  const current = selected.value
  const title = topicDraft.value.trim()
  if (!current || !title || title.length > 120) return
  const result = await action.run(() => api.setTitle(current.session_id, title))
  if (!isTaskSuccess(result) || selected.value?.session_id !== current.session_id) return
  session.session.value = {
    ...selected.value,
    title: result.value.title,
    updated_at: result.value.updated_at,
  }
  showRename.value = false
  await sessions.refresh()
}

async function openSource() {
  if (!selected.value) return
  const id = selected.value.session_id
  const result = await action.run(() => api.source(id))
  if (isTaskSuccess(result) && selected.value?.session_id === id) {
    source.value = result.value
    showSource.value = true
  }
}

async function openWorkflows() {
  showWorkflows.value = true
  const result = await workflowAction.run(() => runsApi.list({ limit: 100 }))
  if (isTaskSuccess(result)) workflowHistory.value = result.value
}

async function continueWorkflow() {
  if (!continueRecord.value || !models.value.some((item) => item.reference === continueModel.value))
    return
  const record = continueRecord.value
  const result = await createAction.run(() =>
    api.create({ workflow_session_id: record.session_id, model: continueModel.value }),
  )
  if (!isTaskSuccess(result)) return
  continueRecord.value = undefined
  showWorkflows.value = false
  await sessions.refresh()
  await router.push(`/agents/${encodeURIComponent(result.value.session_id)}`)
}

function prepareContinue(record: (typeof workflowHistory.value)[number]) {
  continueRecord.value = record
  try {
    continueModel.value = readDefaultAgentModel()
  } catch {
    continueModel.value = ''
    ElMessage.error('无法读取浏览器默认模型，请选择模型')
  }
  if (models.value.some((item) => item.reference === continueModel.value)) void continueWorkflow()
}

function openFile(path: string) {
  filePath.value = path
  if (selected.value) {
    files.reset(selected.value.session_id, path)
    void files.read()
  }
  showFiles.value = true
}

const slashCommands = computed<SlashCommand[]>(() => [
  {
    key: '/fork',
    label: '创建分支',
    description: '从当前检查点派生新会话分支',
    icon: 'fork',
    disabled: !selected.value?.last_checkpoint_at || running.value,
    action: () => void fork(),
  },
  {
    key: '/compact',
    label: '压缩上下文',
    description: '精简早期历史轮次',
    icon: 'zap',
    disabled: !selected.value?.continuable,
    action: () => void compact(),
  },
  {
    key: '/stop',
    label: '暂停/停止',
    description: '立即中断当前轮次生成',
    icon: 'pause',
    shortcut: 'Esc',
    disabled: !running.value,
    action: () => void stop(),
  },
  {
    key: '/new',
    label: '新建会话',
    description: '开启新的 Agent 分析任务',
    icon: 'plus',
    action: () => void openCreate(),
  },
  {
    key: '/resume',
    label: '恢复会话',
    description: '选择历史会话继续讨论',
    icon: 'rotate',
    action: () => {
      showBranches.value = true
    },
  },
  {
    key: '/append',
    label: '追加提示词',
    description: '向运行中的轮次追加补充说明',
    icon: 'enter',
    action: () => {
      commands.draft.value = '/append '
    },
  },
  {
    key: '/file',
    label: '工作区文件',
    description: '查看项目文件',
    icon: 'file',
    action: () => openFile('AGENTS.md'),
  },
  {
    key: '/settings',
    label: '全局设置',
    description: '配置模型参数与工具',
    icon: 'settings',
    action: () => {
      showSettings.value = true
    },
  },
  {
    key: '/workflow',
    label: '工作流历史',
    description: '从运行记录派生会话',
    icon: 'workflow',
    action: () => void openWorkflows(),
  },
  {
    key: '/clear',
    label: '清空草稿',
    description: '清空当前输入',
    icon: 'archive',
    action: () => {
      commands.draft.value = ''
    },
  },
])
</script>

<template>
  <div class="agent-page">
    <PageHeader title="Agent 会话" description="文件优先的多轮深度分析入口">
      <el-button @click="showSettings = true">
        <AppIcon name="settings" size="sm" />
        全局设置
      </el-button>
      <el-button type="primary" :loading="createAction.pending.value" @click="openCreate">
        <AppIcon name="plus" size="sm" />
        新会话
      </el-button>
    </PageHeader>
    <el-alert
      v-if="
        session.error.value ||
        sessions.error.value ||
        settings.query.error.value ||
        commandState.error ||
        commandState.stopError ||
        action.error.value
      "
      :title="
        session.error.value ||
        sessions.error.value ||
        settings.query.error.value ||
        commandState.error ||
        commandState.stopError ||
        action.error.value
      "
      type="error"
      :closable="false"
      class="mb-3"
    />
    <div class="agent-layout">
      <AgentSidebar
        :sessions="sessions.data.value ?? []"
        :selected-id="selected?.session_id"
        @select="select"
        @branches="showBranches = true"
      />
      <main class="agent-main">
        <template v-if="selected">
          <AgentHeader
            :session="selected"
            :models="models"
            :running="running"
            :stream-state="session.state.value"
            @change-model="setModel"
            @open-files="openFile('AGENTS.md')"
            @open-settings="showSettings = true"
            @open-source="openSource"
            @open-workflows="openWorkflows"
            @compact="compact"
            @fork="() => void fork()"
            @rename="openRename"
          />
          <div v-if="!selected.continuable" class="p-3">
            <el-alert
              :title="selected.continuation_error?.message ?? 'checkpoint 不可用，无法继续此会话'"
              type="error"
              :closable="false"
            />
            <el-button size="small" @click="openFile(selected.history_path)">
              读取原始事件文件
            </el-button>
          </div>
          <AgentTranscript
            :events="session.events.value"
            :messages="session.messages.value"
            :tools="settings.query.data.value?.tools"
            :session-id="selected.session_id"
            :running="running"
            :expand-reasoning="expandReasoning"
            @edit="branches.start"
            @fork="fork"
            @file="openFile"
            @resume="() => void session.select(selected!.session_id)"
          />
        </template>
        <div v-else class="agent-empty">
          <AppIcon name="bot" size="lg" />
          <h2>开启 Agent 智能会话</h2>
          <p>选择历史会话，或点击新会话开始分析。</p>
        </div>
        <AgentComposer
          v-model:draft="draft"
          :running="running"
          :disabled="!selected || !selected.continuable || session.state.value === 'loading'"
          :send-uncertain="commandState.uncertain"
          :send-retry-safe="commandState.retrySafe"
          :pending="commandState.pending"
          :stop-pending="commandState.stopPending"
          :commands="slashCommands"
          @send="send"
          @stop="stop"
          @execute-command="(command) => command.action()"
        />
      </main>
    </div>
    <AgentGlobalSettingsModal
      v-if="showSettings"
      v-model="showSettings"
      :controller="settings"
      @changed="refreshDisplayPreferences"
    />
    <el-dialog v-model="showRename" title="命名话题" width="min(90vw, 440px)">
      <el-input
        v-model="topicDraft"
        aria-label="话题名称"
        maxlength="120"
        show-word-limit
        @keydown.enter="renameTopic"
      />
      <template #footer>
        <el-button @click="showRename = false">取消</el-button>
        <el-button
          type="primary"
          :loading="action.pending.value"
          :disabled="!topicDraft.trim()"
          @click="renameTopic"
        >
          保存
        </el-button>
      </template>
    </el-dialog>
    <AgentBranchDrawer
      v-model:visible="showBranches"
      :sessions="sessions.data.value ?? []"
      :selected-session-id="selected?.session_id"
      @select="select"
      @fork="fork"
    />
    <el-drawer
      v-model="showFiles"
      title="Agent 工作区文件"
      size="min(95vw, 720px)"
      destroy-on-close
    >
      <AgentFileDrawer v-if="showFiles && selected" :files="files" />
    </el-drawer>
    <el-drawer v-model="showSource" title="只读 Workflow 来源" size="min(95vw, 640px)">
      <p>Workflow session：{{ source?.workflow_session_id ?? '无' }}</p>
      <p>绑定时间 {{ source?.created_at }}</p>
      <pre>{{ JSON.stringify(source?.input, null, 2) }}</pre>
    </el-drawer>
    <el-drawer v-model="showWorkflows" title="Workflow 历史" size="min(95vw, 640px)">
      <el-alert
        v-if="workflowAction.error.value"
        :title="workflowAction.error.value"
        type="error"
        :closable="false"
      />
      <el-button :loading="workflowAction.pending.value" @click="openWorkflows">刷新历史</el-button>
      <el-empty
        v-if="
          !workflowHistory.length && !workflowAction.pending.value && !workflowAction.error.value
        "
        description="暂无 Workflow 运行记录"
      />
      <article
        v-for="record in workflowHistory"
        :key="record.session_id"
        class="workflow-history-card"
      >
        <router-link :to="`/runs/${record.session_id}`">
          {{ record.workflow_id }} / {{ record.session_id }}
        </router-link>
        <el-button
          v-if="['completed', 'partial'].includes(record.status)"
          @click="prepareContinue(record)"
        >
          继续讨论
        </el-button>
      </article>
    </el-drawer>
    <el-dialog
      :model-value="!!continueRecord"
      title="从 Workflow 结果创建 Agent 会话"
      width="min(90vw, 580px)"
      @close="continueRecord = undefined"
    >
      <p v-if="continueRecord">
        来源 {{ continueRecord.workflow_id }} / {{ continueRecord.session_id }}
      </p>
      <el-select v-model="continueModel" aria-label="续接模型" placeholder="选择模型">
        <el-option
          v-for="item in models"
          :key="item.reference"
          :label="`${item.ai} / ${item.model}`"
          :value="item.reference"
        />
      </el-select>
      <el-alert
        v-if="createAction.error.value"
        :title="createAction.error.value"
        type="error"
        :closable="false"
      />
      <template #footer>
        <el-button @click="continueRecord = undefined">取消</el-button>
        <el-button
          type="primary"
          :loading="createAction.pending.value"
          :disabled="!models.some((item) => item.reference === continueModel)"
          @click="continueWorkflow"
        >
          创建并继续
        </el-button>
      </template>
    </el-dialog>
    <AgentCreateDialog
      v-model="showCreate"
      v-model:model="model"
      :models="models"
      :pending="createAction.pending.value"
      :error="createAction.error.value || settings.query.error.value"
      @create="create"
    />
    <AgentEditBranchDialog
      :controller="branches"
      @confirm="
        async () => {
          const child = await branches.confirm()
          if (child) {
            await sessions.refresh()
            select(child)
          }
        }
      "
    />
  </div>
</template>

<style scoped>
.agent-page {
  display: flex;
  flex-direction: column;
  height: calc(100dvh - 120px);
  min-height: 520px;
}
.agent-layout {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  flex: 1;
  min-height: 0;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  background: var(--surface);
}
.agent-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}
.agent-empty {
  flex: 1;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 8px;
  color: var(--muted);
  text-align: center;
}
.agent-empty h2 {
  margin: 8px 0 0;
  color: var(--el-text-color-primary);
}
.workflow-history-card {
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
@media (max-width: 768px) {
  .agent-layout {
    grid-template-columns: 1fr;
  }
  .agent-sidebar {
    display: none;
  }
}
</style>
