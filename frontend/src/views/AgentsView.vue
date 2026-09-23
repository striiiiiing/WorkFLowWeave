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
import AgentHeader from '@/components/agent/AgentHeader.vue'
import AgentTranscript from '@/components/agent/AgentTranscript.vue'
import AgentComposer from '@/components/agent/AgentComposer.vue'
import AgentBranchDrawer from '@/components/agent/AgentBranchDrawer.vue'
import AgentGlobalSettingsModal from '@/components/agent/AgentGlobalSettingsModal.vue'
import AgentFileDrawer from '@/components/agent/AgentFileDrawer.vue'
import AgentContinueButton from '@/components/agent/AgentContinueButton.vue'
import AppIcon from '@/components/icons/AppIcon.vue'
import type { SlashCommand } from '@/components/agent/AgentSlashMenu.vue'
import type { SessionRecord } from '@/types'
import { ApiError } from '@/api/client'
import { ElMessage } from 'element-plus'

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
const sessionSearch = ref('')
const showCreate = ref(false)
const showBranches = ref(false)
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
const availableModels = computed(() => settings.data.value?.models ?? [])

const filteredSessions = computed(() => {
  const list = sessions.data.value ?? []
  const q = sessionSearch.value.trim().toLowerCase()
  if (!q) return list
  return list.filter(
    (s) =>
      s.session_id.toLowerCase().includes(q) ||
      (s.branch_id && s.branch_id.toLowerCase().includes(q)) ||
      (s.model && s.model.toLowerCase().includes(q)),
  )
})

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
  showBranches.value = false
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
  ElMessage.success('已创建新会话')
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

async function stop() {
  if (!selected.value) return
  const result = await stopAction.run(() => agentsApi.cancel(selected.value!.session_id))
  if (result && selected.value?.session_id === result.session_id) selected.value = result
  ElMessage.warning('会话执行已暂停 / 停止')
}

async function compact() {
  if (!selected.value) return
  const result = await action.run(() => agentsApi.compact(selected.value!.session_id))
  if (result && selected.value?.session_id === result.session_id) {
    selected.value = { ...selected.value, status: 'running', turn_id: result.turn_id }
    stream.resume(result.turn_id)
    ElMessage.success('⚡ 上下文智能压缩已触发，将在新轮次完成归档')
  }
}

async function fork(targetSession?: AgentSession) {
  const session = targetSession ?? selected.value
  if (!session) return
  const child = await action.run(() => agentsApi.fork(session.session_id))
  if (child) {
    await sessions.refresh()
    await select(child)
    ElMessage.success(`已派生新分支：${child.branch_id}`)
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
    ElMessage.success(`已创建分支并重新发送指令：${child.branch_id}`)
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
    ElMessage.success(`已更新下轮模型：${value}`)
  }
}

// 斜杠快捷指令配置
const slashCommands: SlashCommand[] = [
  {
    key: '/fork',
    label: '创建分支',
    description: '从当前检查点派生新会话分支',
    icon: 'fork',
    shortcut: '⌘+F',
    action: () => fork(),
  },
  {
    key: '/compact',
    label: '压缩上下文',
    description: '精简早期历史轮次，腾出 Token 空间',
    icon: 'zap',
    badge: '减省 Token',
    action: () => compact(),
  },
  {
    key: '/stop',
    label: '暂停/停止',
    description: '立即中断当前轮次生成',
    icon: 'pause',
    shortcut: 'Esc',
    action: () => stop(),
  },
  {
    key: '/resume',
    label: '恢复会话',
    description: '从当前中断位置继续执行',
    icon: 'rotate',
    action: () => {
      draft.value = '/resume '
    },
  },
  {
    key: '/new',
    label: '新建会话',
    description: '开启新的 Agent 分析任务',
    icon: 'plus',
    action: () => {
      showCreate.value = true
    },
  },
  {
    key: '/append',
    label: '追加提示词',
    description: '在运行中的轮次安全追加补充说明',
    icon: 'enter',
    action: () => {
      draft.value = '/append '
    },
  },
  {
    key: '/file',
    label: '工作区文件',
    description: '查看项目文件与运行产物 Artifact',
    icon: 'file',
    action: () => {
      openFile('AGENTS.md')
    },
  },
  {
    key: '/settings',
    label: '全局设置',
    description: '配置模型参数、上下文预算、沙箱与工具',
    icon: 'settings',
    action: () => {
      showSettings.value = true
    },
  },
  {
    key: '/workflow',
    label: '工作流历史',
    description: '从 Workflow 运行记录派生会话',
    icon: 'workflow',
    action: () => {
      draft.value = '/workflow'
      void send()
    },
  },
  {
    key: '/clear',
    label: '清空草稿',
    description: '重置输入框内容',
    icon: 'archive',
    action: () => {
      draft.value = ''
    },
  },
]

function executeSlashCommand(cmd: SlashCommand) {
  cmd.action()
}
</script>

<template>
  <div class="agent-view-shell">
    <PageHeader title="Agent 会话" description="文件优先的多轮深度分析入口">
      <router-link to="/agent-demo">
        <el-button type="success" plain size="small">
          <AppIcon name="sparkles" size="sm" />
          <span>查看 ChatGPT 交互演示</span>
        </el-button>
      </router-link>
      <el-button class="mobile-toggle-btn" @click="showBranches = true">
        <AppIcon name="fork" size="sm" />
        <span>分支树</span>
      </el-button>
      <el-button type="primary" @click="showCreate = true">
        <AppIcon name="plus" size="sm" />
        <span>新会话</span>
      </el-button>
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
      class="mb-3"
    />

    <div class="chatgpt-layout">
      <!-- 1. ChatGPT 风格侧栏 -->
      <aside class="chatgpt-sidebar">
        <div class="sidebar-header">
          <button type="button" class="sidebar-new-btn" @click="showCreate = true">
            <AppIcon name="plus" size="sm" />
            <span>新会话</span>
          </button>
        </div>

        <div class="sidebar-search-box">
          <el-input
            v-model="sessionSearch"
            placeholder="搜索会话与分支..."
            size="small"
            clearable
          >
            <template #prefix>
              <AppIcon name="search" size="sm" />
            </template>
          </el-input>
        </div>

        <nav class="sidebar-sessions-list" aria-label="会话列表">
          <div class="list-section-title">会话与分支</div>
          <button
            v-for="s in filteredSessions"
            :key="s.session_id"
            type="button"
            class="sidebar-session-item"
            :class="{ active: selected?.session_id === s.session_id }"
            @click="select(s)"
          >
            <span class="session-icon">
              <AppIcon :name="s.parent_session_id ? 'fork' : 'bot'" size="sm" />
            </span>
            <div class="session-info">
              <strong>{{ s.branch_id || 'main' }}</strong>
              <small>{{ s.session_id.slice(0, 14) }}...</small>
            </div>
            <span class="session-badge" :class="s.status" />
          </button>

          <el-empty
            v-if="!filteredSessions.length"
            description="暂无会话"
            :image-size="48"
          />
        </nav>

        <div class="sidebar-bottom-actions">
          <button type="button" class="sidebar-action-btn" @click="showBranches = true">
            <AppIcon name="fork" size="sm" />
            <span>分支拓扑树</span>
          </button>
          <button type="button" class="sidebar-action-btn" @click="showSettings = true">
            <AppIcon name="settings" size="sm" />
            <span>全局设置</span>
          </button>
        </div>
      </aside>

      <!-- 2. 主聊天视窗 -->
      <main class="chatgpt-main">
        <template v-if="selected">
          <!-- 极简 ChatGPT 顶部栏 -->
          <AgentHeader
            :session="selected"
            :models="availableModels"
            :running="running"
            :stream-state="stream.state.value"
            @change-model="setModel"
            @open-branches="showBranches = true"
            @open-files="openFile('AGENTS.md')"
            @open-settings="showSettings = true"
            @open-source="openSource"
            @open-workflows="showWorkflows = true"
            @compact="compact"
            @fork="fork()"
          />

          <!-- 不可继续警告 -->
          <div v-if="!selected.continuable" class="p-3">
            <el-alert
              :title="selected.continuation_error?.message ?? 'checkpoint 不可用，无法继续此会话'"
              type="error"
              :closable="false"
            />
            <el-button class="mt-2" size="small" @click="openFile(selected.history_path)">
              读取原始事件文件
            </el-button>
          </div>

          <!-- 消息历史流水 -->
          <AgentTranscript
            :events="stream.events.value"
            :tools="settings.data.value?.tools"
            :session-id="selected.session_id"
            :running="running"
            @edit="edit"
            @fork="fork()"
            @file="openFile"
            @resume="sessionQuery.refresh"
          />
        </template>

        <!-- 无选中会话状态 -->
        <div v-else class="empty-selection-view">
          <div class="empty-icon-card">
            <AppIcon name="bot" size="lg" />
          </div>
          <h2>开启 Agent 智能会话</h2>
          <p>
            选择左侧历史会话，或点击下方按钮开启新分析。支持输入 <code>/</code> 唤起快捷指令。
          </p>
          <div class="flex gap-2 mt-4">
            <el-button type="primary" @click="showCreate = true">
              <AppIcon name="plus" size="sm" />
              <span>新建会话</span>
            </el-button>
            <router-link to="/agent-demo">
              <el-button>
                <AppIcon name="sparkles" size="sm" />
                <span>体验 ChatGPT 交互演示</span>
              </el-button>
            </router-link>
          </div>
        </div>

        <!-- ChatGPT 风格底部输入器 -->
        <AgentComposer
          v-model:draft="draft"
          :running="running"
          :disabled="selected?.continuable === false"
          :send-uncertain="sendUncertain"
          :pending="action.pending.value"
          :stop-pending="stopAction.pending.value"
          :commands="slashCommands"
          @send="send"
          @stop="stop"
          @execute-command="executeSlashCommand"
        />
      </main>
    </div>

    <!-- 3. 全局设置抽屉/模态框 -->
    <AgentGlobalSettingsModal
      v-model="showSettings"
      @changed="settings.refresh"
    />

    <!-- 4. 可视化分支图谱抽屉 -->
    <AgentBranchDrawer
      v-model:visible="showBranches"
      :sessions="sessions.data.value ?? []"
      :selected-session-id="selected?.session_id"
      @select="select"
      @fork="fork"
    />

    <!-- 5. 工作区文件与产物抽屉 -->
    <el-drawer v-model="showFiles" title="Agent 工作区文件" size="min(95vw, 720px)" destroy-on-close>
      <AgentFileDrawer
        v-if="selected && showFiles"
        :session-id="selected.session_id"
        :initial-path="filePath"
      />
    </el-drawer>

    <!-- 6. 只读 Workflow 来源抽屉 -->
    <el-drawer v-model="showSource" title="只读 Workflow 来源" size="min(95vw, 640px)">
      <p>Workflow session：{{ source?.workflow_session_id ?? '无' }}</p>
      <p>绑定时间 {{ source?.created_at }}</p>
      <p>模型 {{ selected?.model }}</p>
      <pre>{{ JSON.stringify(source?.input, null, 2) }}</pre>
    </el-drawer>

    <!-- 7. Workflow 历史记录抽屉 -->
    <el-drawer v-model="showWorkflows" title="Workflow 历史" size="min(95vw, 640px)">
      <p class="text-sm text-muted mb-3">使用 /workflow &lt;session_id&gt; 从指定最终结果创建会话：</p>
      <article
        v-for="record in workflowHistory"
        :key="record.session_id"
        class="workflow-history-card"
      >
        <router-link :to="`/runs/${record.session_id}`">
          {{ record.workflow_id }} / {{ record.session_id }}
        </router-link>
        <p class="text-xs text-muted mt-1">
          {{ record.status }} · {{ record.finished_at ?? record.updated_at }}
        </p>
        <AgentContinueButton
          v-if="['completed', 'partial'].includes(record.status)"
          :workflow-session-id="record.session_id"
          class="mt-2"
        />
      </article>
    </el-drawer>

    <!-- 8. 创建新会话 Dialog -->
    <el-dialog v-model="showCreate" title="创建 Agent 分析会话" width="min(90vw, 500px)">
      <el-form label-position="top">
        <el-form-item label="初始模型选择（可沿用系统默认）">
          <el-select
            v-model="model"
            placeholder="选择模型（可选）"
            clearable
            class="w-full"
            aria-label="新会话模型"
          >
            <el-option
              v-for="item in availableModels"
              :key="item.reference"
              :value="item.reference"
              :label="`${item.provider} / ${item.model || item.reference}`"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="action.pending.value" @click="create">
          确认创建
        </el-button>
      </template>
    </el-dialog>

    <!-- 9. 编辑消息并创建分支 Dialog -->
    <el-dialog
      :model-value="!!editEvent"
      title="编辑指令并派生新分支"
      width="min(90vw, 620px)"
      @close="editEvent = undefined"
    >
      <p class="text-sm text-muted mb-2">
        将从此消息节点创建全新的独立分支，并发送更新后的指令；原始分支与工具回执不受影响。
      </p>
      <el-input v-model="editText" type="textarea" :rows="6" aria-label="分支消息" />
      <template #footer>
        <el-button @click="editEvent = undefined">取消</el-button>
        <el-button type="primary" :loading="action.pending.value" @click="confirmEdit">
          确认创建分支并发送
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.agent-view-shell {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 84px);
}

.chatgpt-layout {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  flex: 1;
  min-height: 0;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface);
  overflow: hidden;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.03);
}

/* Sidebar */
.chatgpt-sidebar {
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
  background: var(--el-fill-color-light);
  overflow: hidden;
}

.sidebar-header {
  padding: 12px;
}

.sidebar-new-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 8px 14px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--el-text-color-primary);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.sidebar-new-btn:hover {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary) 5%, var(--surface));
}

.sidebar-search-box {
  padding: 0 12px 10px;
}

.sidebar-sessions-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.list-section-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
  letter-spacing: 0.04em;
  padding: 6px 8px 4px;
}

.sidebar-session-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: all 0.12s ease;
}

.sidebar-session-item:hover {
  background: var(--surface);
  border-color: var(--border);
}

.sidebar-session-item.active {
  background: var(--surface);
  border-color: color-mix(in srgb, var(--el-color-primary) 40%, transparent);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
}

.session-icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: var(--el-fill-color);
  color: var(--muted);
  flex-shrink: 0;
}

.sidebar-session-item.active .session-icon {
  background: color-mix(in srgb, var(--el-color-primary) 12%, transparent);
  color: var(--el-color-primary);
}

.session-info {
  flex: 1;
  min-width: 0;
}

.session-info strong {
  display: block;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-info small {
  display: block;
  font-size: 11px;
  color: var(--muted);
  font-family: ui-monospace, monospace;
}

.session-badge {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #cbd5e1;
}

.session-badge.running {
  background: #10b981;
  box-shadow: 0 0 6px #10b981;
}

.sidebar-bottom-actions {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border-top: 1px solid var(--border);
}

.sidebar-action-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 8px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.sidebar-action-btn:hover {
  background: var(--surface);
  color: var(--el-text-color-primary);
}

/* Main Column */
.chatgpt-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100%;
  background: var(--surface);
}

.empty-selection-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 32px 16px;
  color: var(--muted);
}

.empty-icon-card {
  display: grid;
  place-items: center;
  width: 64px;
  height: 64px;
  border-radius: 20px;
  background: color-mix(in srgb, var(--el-color-primary) 12%, transparent);
  color: var(--el-color-primary);
  margin-bottom: 16px;
}

.empty-selection-view h2 {
  font-size: 20px;
  color: var(--el-text-color-primary);
  margin: 0 0 8px;
}

.empty-selection-view p {
  font-size: 13px;
  max-width: 420px;
  line-height: 1.6;
  margin: 0;
}

.empty-selection-view code {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--el-fill-color);
  font-family: ui-monospace, monospace;
}

.workflow-history-card {
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 10px;
}

.mobile-toggle-btn {
  display: none;
}

@media (max-width: 768px) {
  .chatgpt-layout {
    grid-template-columns: 1fr;
  }
  .chatgpt-sidebar {
    display: none;
  }
  .mobile-toggle-btn {
    display: inline-flex;
  }
}
</style>
