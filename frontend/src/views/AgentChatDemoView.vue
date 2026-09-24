<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import AppIcon from '@/shared/ui/icons/AppIcon.vue'
import PageHeader from '@/shared/ui/PageHeader.vue'
import AgentHeader from '@/components/agent/AgentHeader.vue'
import AgentComposer from '@/components/agent/AgentComposer.vue'
import AgentTranscript from '@/components/agent/AgentTranscript.vue'
import AgentBranchDrawer from '@/components/agent/AgentBranchDrawer.vue'
import AgentGlobalSettingsModal from '@/components/agent/AgentGlobalSettingsModal.vue'
import type { SlashCommand } from '@/components/agent/AgentSlashMenu.vue'
import type { AgentEvent, AgentModel, AgentSession } from '@/api/agents'

// 1. 模拟模型列表
const availableModels: AgentModel[] = [
  { reference: 'deepseek-r1', provider: 'deepseek', ai: 'deepseek-api', model: 'DeepSeek-R1 (推理增强)' },
  { reference: 'qwen-2.5-72b', provider: 'alibaba', ai: 'dashscope', model: 'Qwen 2.5 72B (日志专精)' },
  { reference: 'gpt-4o', provider: 'openai', ai: 'openai-compatible', model: 'GPT-4o (通用分析)' },
  { reference: 'claude-3-5-sonnet', provider: 'anthropic', ai: 'bedrock', model: 'Claude 3.5 Sonnet' },
]

// 2. 模拟分支会话树
const mockSessions = ref<AgentSession[]>([
  {
    session_id: 'session-demo-001',
    branch_id: 'main',
    model: 'deepseek-r1',
    workflow_session_id: 'wf-run-8821',
    created_at: new Date(Date.now() - 3600000 * 2).toISOString(),
    updated_at: new Date().toISOString(),
    status: 'completed',
    turn_id: 'turn-3',
    parent_session_id: null,
    continuable: true,
    history_path: 'data/history/session-demo-001.jsonl',
    last_checkpoint_at: new Date().toISOString(),
    context_budget: {
      messages: 8420,
      system: 1850,
      tools: 2600,
      output: 4096,
      total: 16966,
      window: 65536,
      trigger: 48000,
      remaining: 48570,
      estimated: false,
      token_counter: 'tiktoken',
    },
  },
  {
    session_id: 'session-demo-002',
    branch_id: 'branch-db-slowquery',
    model: 'qwen-2.5-72b',
    workflow_session_id: 'wf-run-8821',
    created_at: new Date(Date.now() - 1800000).toISOString(),
    updated_at: new Date().toISOString(),
    status: 'running',
    turn_id: 'turn-4',
    parent_session_id: 'session-demo-001',
    continuable: true,
    history_path: 'data/history/session-demo-002.jsonl',
    last_checkpoint_at: new Date().toISOString(),
    context_budget: {
      messages: 12400,
      system: 1850,
      tools: 2600,
      output: 4096,
      total: 20946,
      window: 65536,
      trigger: 48000,
      remaining: 44590,
      estimated: false,
      token_counter: 'tiktoken',
    },
  },
  {
    session_id: 'session-demo-003',
    branch_id: 'branch-oom-crash',
    model: 'claude-3-5-sonnet',
    workflow_session_id: null,
    created_at: new Date(Date.now() - 86400000).toISOString(),
    updated_at: new Date(Date.now() - 80000000).toISOString(),
    status: 'completed',
    turn_id: 'turn-2',
    parent_session_id: null,
    continuable: true,
    history_path: 'data/history/session-demo-003.jsonl',
    last_checkpoint_at: new Date(Date.now() - 80000000).toISOString(),
    context_budget: {
      messages: 6200,
      system: 1850,
      tools: 1200,
      output: 4096,
      total: 13346,
      window: 128000,
      trigger: 96000,
      remaining: 114654,
      estimated: false,
      token_counter: 'tiktoken',
    },
  },
])

const currentSessionId = ref('session-demo-001')
const currentSession = computed(() => {
  return mockSessions.value.find((s) => s.session_id === currentSessionId.value) ?? mockSessions.value[0]
})

// 3. 模拟对话事件流数据 (包含用户、助手、并行只读工具、独占写工具和智能压缩)
const sessionEventsMap = ref<Record<string, AgentEvent[]>>({
  'session-demo-001': [
    {
      id: 1,
      session_id: 'session-demo-001',
      turn_id: 'turn-1',
      type: 'message.user',
      at: '2026-09-23T14:10:00Z',
      data: {
        text: '检查过去 2 小时服务集群的核心错误日志，并排查订单处理阶段的异常突增。',
        message_id: 'msg-u1',
      },
    },
    {
      id: 2,
      session_id: 'session-demo-001',
      turn_id: 'turn-1',
      type: 'tool.queued',
      at: '2026-09-23T14:10:02Z',
      data: {
        tool_call_id: 'tc-read-logs',
        name: 'logs_collector',
        execution: 'read',
        arguments: { levels: ['ERROR', 'CRITICAL'], max_lines: 300, module: 'order-service' },
      },
    },
    {
      id: 3,
      session_id: 'session-demo-001',
      turn_id: 'turn-1',
      type: 'tool.queued',
      at: '2026-09-23T14:10:02Z',
      data: {
        tool_call_id: 'tc-metrics',
        name: 'metrics_collector',
        execution: 'read',
        arguments: { metric: 'http_server_requests_5xx', duration: '2h' },
      },
    },
    {
      id: 4,
      session_id: 'session-demo-001',
      turn_id: 'turn-1',
      type: 'tool.completed',
      at: '2026-09-23T14:10:05Z',
      data: {
        tool_call_id: 'tc-read-logs',
        name: 'logs_collector',
        execution: 'read',
        result: {
          status: 'success',
          matched_lines: 48,
          duration_ms: 124,
          sample: 'ConnectionTimeoutException: MySQL Pool exhausted at OrderService.checkout()',
        },
      },
    },
    {
      id: 5,
      session_id: 'session-demo-001',
      turn_id: 'turn-1',
      type: 'tool.completed',
      at: '2026-09-23T14:10:06Z',
      data: {
        tool_call_id: 'tc-metrics',
        name: 'metrics_collector',
        execution: 'read',
        result: { status: 'success', peak_qps: 1840, error_ratio: '14.2%', duration_ms: 88 },
      },
    },
    {
      id: 6,
      session_id: 'session-demo-001',
      turn_id: 'turn-1',
      type: 'message.completed',
      at: '2026-09-23T14:10:10Z',
      data: {
        message_id: 'msg-a1',
        text: `### 诊断发现：数据库连接池耗尽告警\n\n已聚合过去 2 小时的日志与指标：\n1. **错误定位**：\`order-service\` 在 \`14:02 - 14:38\` 期间突发 48 次 \`ConnectionTimeoutException\`。\n2. **根本成因**：由于大促预热流量冲击，HikariCP 数据库连接池（最大上限 30）在长事务查询下被占满。\n3. **影响范围**：订单结算接口 500 比例升至 14.2%，已有 128 位用户受影响重试。`,
      },
    },
    // 上下文压缩里程碑事件
    {
      id: 7,
      session_id: 'session-demo-001',
      turn_id: 'turn-2',
      type: 'context.compacted',
      at: '2026-09-23T14:15:00Z',
      data: {
        source_event_range: [1, 6],
        artifact_path: 'summaries/turn-1-compacted.md',
        summary:
          '前置排查已锁定 MySQL 连接池耗尽（48次报错），已归档早期原始事件，保留当前连接池参数与排查上下文，释放 14,200 Tokens。',
      },
    },
    {
      id: 8,
      session_id: 'session-demo-001',
      turn_id: 'turn-3',
      type: 'message.user',
      at: '2026-09-23T14:16:00Z',
      data: {
        text: '尝试临时扩大连接池并查看当前数据库等待队列状态。',
        message_id: 'msg-u2',
      },
    },
    {
      id: 9,
      session_id: 'session-demo-001',
      turn_id: 'turn-3',
      type: 'tool.completed',
      at: '2026-09-23T14:16:04Z',
      data: {
        tool_call_id: 'tc-write-pool',
        name: 'config_writer',
        execution: 'exclusive',
        arguments: { target: 'application-prod.yml', key: 'datasource.hikari.maximum-pool-size', value: 60 },
        result: { status: 'success', backup_hash: '9a8f3b', duration_ms: 65, artifact_path: 'diffs/hikari-patch.diff' },
      },
    },
    {
      id: 10,
      session_id: 'session-demo-001',
      turn_id: 'turn-3',
      type: 'message.completed',
      at: '2026-09-23T14:16:08Z',
      data: {
        message_id: 'msg-a2',
        text: `已安全完成热配置调整：\n- **连接池容量**：由 \`30\` 提升至 \`60\`。\n- **沙箱隔离**：写入受 Bubblewrap 限制，已留存 \`hikari-patch.diff\` 备份。\n- **排队现状**：等待队列当前已下降至 0，接口 P99 延迟已恢复至 45ms 标准区间。`,
      },
    },
  ],
  'session-demo-002': [
    {
      id: 101,
      session_id: 'session-demo-002',
      turn_id: 'turn-4',
      type: 'message.user',
      at: '2026-09-23T14:40:00Z',
      data: {
        text: '从上一轮分支派生，单独针对慢查询 SQL 进行 EXPLAIN 执行计划深度解析。',
        message_id: 'msg-u3',
      },
    },
    {
      id: 102,
      session_id: 'session-demo-002',
      turn_id: 'turn-4',
      type: 'message.completed',
      at: '2026-09-23T14:40:06Z',
      data: {
        message_id: 'msg-a3',
        text: `正在分析慢 SQL：\`SELECT * FROM orders WHERE user_id = ? AND status = 1 ORDER BY create_time DESC\`\n\n- **扫描行数**：450,000+ 行（全表扫描）\n- **缺失索引**：建议联合索引 \`idx_user_status_ctime(user_id, status, create_time)\`，预估可减少 98% 锁等待时间。`,
      },
    },
  ],
})

const currentEvents = computed(() => sessionEventsMap.value[currentSessionId.value] ?? [])

// 4. 输入框与状态
const draft = ref('')
const isRunning = ref(false)
const showBranches = ref(false)
const showSettings = ref(false)
const showFiles = ref(false)
const showWorkflowDrawer = ref(false)
const sessionSearch = ref('')
const simulatedTimer = ref<ReturnType<typeof setInterval> | null>(null)

// 5. 斜杠指令注册
const slashCommands: SlashCommand[] = [
  {
    key: '/fork',
    label: '创建分支',
    description: '从当前检查点派生新分支，尝试不同修复策略',
    icon: 'fork',
    shortcut: '⌘+F',
    action: () => forkCurrentSession(),
  },
  {
    key: '/compact',
    label: '压缩上下文',
    description: '智能精简早期历史轮次，腾出 Token 窗口',
    icon: 'zap',
    badge: '减省 Token',
    action: () => compactContext(),
  },
  {
    key: '/stop',
    label: '暂停/停止',
    description: '立即中断正在运行的 Agent 分析生成',
    icon: 'pause',
    shortcut: 'Esc',
    action: () => stopGeneration(),
  },
  {
    key: '/resume',
    label: '恢复会话',
    description: '从中断的检查点恢复执行与分析',
    icon: 'rotate',
    action: () => resumeSession(),
  },
  {
    key: '/new',
    label: '新建会话',
    description: '开启全新的 Agent 多轮分析任务',
    icon: 'plus',
    action: () => createNewSession(),
  },
  {
    key: '/file',
    label: '工作区文件',
    description: '查看诊断产物、代码补丁与运行时数据',
    icon: 'file',
    action: () => {
      showFiles.value = true
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
    label: '关联工作流',
    description: '导入历史 Workflow 诊断报告作为起点',
    icon: 'workflow',
    action: () => {
      showWorkflowDrawer.value = true
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

// 6. 交互逻辑实现
function selectSession(session: AgentSession) {
  currentSessionId.value = session.session_id
  showBranches.value = false
  ElMessage.info(`已切换至分支：${session.branch_id}`)
}

function createNewSession() {
  const newId = `session-demo-${Date.now().toString().slice(-4)}`
  const newSession: AgentSession = {
    session_id: newId,
    branch_id: 'main',
    model: 'deepseek-r1',
    workflow_session_id: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    status: 'completed',
    turn_id: 'turn-0',
    parent_session_id: null,
    continuable: true,
    history_path: `data/history/${newId}.jsonl`,
    last_checkpoint_at: new Date().toISOString(),
    context_budget: {
      messages: 0,
      system: 1850,
      tools: 2600,
      output: 4096,
      total: 4450,
      window: 65536,
      trigger: 48000,
      remaining: 61086,
      estimated: false,
      token_counter: 'tiktoken',
    },
  }
  mockSessions.value.unshift(newSession)
  sessionEventsMap.value[newId] = []
  currentSessionId.value = newId
  ElMessage.success('已新建会话')
}

function forkCurrentSession() {
  const parent = currentSession.value
  const branchNum = mockSessions.value.length + 1
  const forkId = `session-demo-fork-${branchNum}`
  const forkedSession: AgentSession = {
    session_id: forkId,
    branch_id: `branch-v${branchNum}`,
    model: parent.model,
    workflow_session_id: parent.workflow_session_id,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    status: 'completed',
    turn_id: parent.turn_id,
    parent_session_id: parent.session_id,
    continuable: true,
    history_path: `data/history/${forkId}.jsonl`,
    last_checkpoint_at: new Date().toISOString(),
    context_budget: structuredClone(parent.context_budget),
  }
  mockSessions.value.push(forkedSession)
  sessionEventsMap.value[forkId] = structuredClone(currentEvents.value)
  currentSessionId.value = forkId
  ElMessage.success(`已派生新分支：${forkedSession.branch_id}`)
}

function compactContext() {
  if (!currentSession.value.continuable) return
  const events = sessionEventsMap.value[currentSessionId.value]
  if (!events || events.length === 0) {
    ElMessage.warning('当前会话暂无早期历史可压缩')
    return
  }

  const compactEvent: AgentEvent = {
    id: events.length + 1,
    session_id: currentSessionId.value,
    turn_id: currentSession.value.turn_id ?? 'turn-compact',
    type: 'context.compacted',
    at: new Date().toISOString(),
    data: {
      source_event_range: [1, events.length],
      artifact_path: `summaries/compact-${Date.now()}.md`,
      summary: '通过智能分析归档了前面的轮次历史，保留核心诊断结论与模型上下文，成功腾出空间。',
    },
  }

  events.push(compactEvent)

  // 释放 Token
  if (currentSession.value.context_budget) {
    currentSession.value.context_budget.messages = Math.round(
      currentSession.value.context_budget.messages * 0.35,
    )
    currentSession.value.context_budget.total =
      currentSession.value.context_budget.messages +
      currentSession.value.context_budget.system +
      currentSession.value.context_budget.tools
  }

  ElMessage.success('⚡ 上下文已智能压缩，已在信息流中生成归档里程碑')
}

function handleSendMessage() {
  const text = draft.value.trim()
  if (!text || isRunning.value) return

  draft.value = ''
  const events = sessionEventsMap.value[currentSessionId.value] ?? []

  // 1. 添加用户消息
  const userEventId = events.length + 1
  events.push({
    id: userEventId,
    session_id: currentSessionId.value,
    turn_id: `turn-${userEventId}`,
    type: 'message.user',
    at: new Date().toISOString(),
    data: { text, message_id: `msg-u${userEventId}` },
  })

  // 2. 模拟思考与流式输出
  isRunning.value = true
  const assistantEventId = userEventId + 1
  let tokenIndex = 0
  const replyTokens = [
    '收到你的指令。',
    '正在通过日志采集插件定位问题...',
    '分析完成：发现 2 处潜在死锁隐患。',
    '已生成优化建议与索引补丁。',
  ]

  simulatedTimer.value = setInterval(() => {
    if (tokenIndex < replyTokens.length) {
      if (tokenIndex === 0) {
        events.push({
          id: assistantEventId,
          session_id: currentSessionId.value,
          turn_id: `turn-${userEventId}`,
          type: 'message.completed',
          at: new Date().toISOString(),
          data: {
            message_id: `msg-a${assistantEventId}`,
            text: replyTokens[0],
          },
        })
      } else {
        const lastMsg = events[events.length - 1]
        if (lastMsg && lastMsg.type === 'message.completed') {
          lastMsg.data.text += '\n\n' + replyTokens[tokenIndex]
        }
      }
      tokenIndex++
    } else {
      stopGeneration(false)
    }
  }, 900)
}

function stopGeneration(notify = true) {
  if (simulatedTimer.value) {
    clearInterval(simulatedTimer.value)
    simulatedTimer.value = null
  }
  isRunning.value = false
  if (notify) {
    const events = sessionEventsMap.value[currentSessionId.value]
    if (events) {
      events.push({
        id: events.length + 1,
        session_id: currentSessionId.value,
        turn_id: currentSession.value.turn_id ?? 'turn-stop',
        type: 'turn.cancelled',
        at: new Date().toISOString(),
        data: { text: 'cancelled' },
      })
    }
    ElMessage.warning('会话执行已暂停 / 停止')
  }
}

function resumeSession() {
  ElMessage.success('已恢复会话状态')
}

function handleExecuteCommand(cmd: SlashCommand) {
  draft.value = ''
  cmd.action()
}

function handleModelChange(newModel: string) {
  currentSession.value.model = newModel
  ElMessage.success(`已切换下轮执行模型为：${newModel}`)
}

function handleMessageEdit(event: AgentEvent) {
  forkCurrentSession()
  draft.value = String(event.data.text ?? '')
  ElMessage.info('已复制旧指令并派生新分支，可修改后重新发送')
}
</script>

<template>
  <div class="chatgpt-demo-wrapper">
    <PageHeader
      title="Agent 会话 (ChatGPT 设计演示)"
      description="基于 ChatGPT 交互标准重构：斜杠快捷指令、全局配置收敛、可视化分支与上下文压缩里程碑"
    >
      <el-tag type="success" effect="plain" class="demo-tag">交互演示版</el-tag>
      <el-button @click="showSettings = true">
        <AppIcon name="settings" size="sm" />
        <span>全局设置</span>
      </el-button>
      <el-button type="primary" @click="createNewSession">
        <AppIcon name="plus" size="sm" />
        <span>新建会话</span>
      </el-button>
    </PageHeader>

    <div class="chatgpt-chat-container">
      <!-- 1. 左侧 ChatGPT 风格会话与分支抽屉/列表 -->
      <aside class="chat-sidebar">
        <div class="sidebar-top">
          <button type="button" class="new-chat-btn" @click="createNewSession">
            <AppIcon name="plus" size="sm" />
            <span>新会话</span>
          </button>
        </div>

        <div class="sidebar-search">
          <el-input
            v-model="sessionSearch"
            placeholder="搜索历史会话..."
            size="small"
            clearable
          >
            <template #prefix>
              <AppIcon name="search" size="sm" />
            </template>
          </el-input>
        </div>

        <div class="sidebar-sessions" role="list">
          <div class="group-title">活跃与衍生分支</div>
          <button
            v-for="s in mockSessions"
            :key="s.session_id"
            type="button"
            class="session-nav-item"
            :class="{ active: s.session_id === currentSessionId }"
            @click="selectSession(s)"
          >
            <span class="session-nav-icon">
              <AppIcon :name="s.parent_session_id ? 'fork' : 'bot'" size="sm" />
            </span>
            <div class="session-nav-meta">
              <strong>{{ s.branch_id || 'main' }}</strong>
              <small>{{ s.session_id.slice(0, 14) }}...</small>
            </div>
            <span class="session-status-dot" :class="s.status" />
          </button>
        </div>

        <div class="sidebar-footer">
          <button type="button" class="sidebar-footer-btn" @click="showBranches = true">
            <AppIcon name="fork" size="sm" />
            <span>分支执行拓扑图</span>
          </button>
        </div>
      </aside>

      <!-- 2. 主聊天视窗 -->
      <main class="chat-main-column">
        <!-- ChatGPT 风格顶部条 -->
        <AgentHeader
          :session="currentSession"
          :models="availableModels"
          :running="isRunning"
          stream-state="connected"
          @change-model="handleModelChange"
          @open-branches="showBranches = true"
          @open-files="showFiles = true"
          @open-settings="showSettings = true"
          @open-source="ElMessage.info('只读 Workflow 来源信息')"
          @open-workflows="showWorkflowDrawer = true"
          @compact="compactContext"
          @fork="forkCurrentSession"
        />

        <!-- 对话消息流水 (带头像、hover 复制与分支、压缩里程碑、工具卡片) -->
        <AgentTranscript
          :events="currentEvents"
          :session-id="currentSession.session_id"
          :running="isRunning"
          @edit="handleMessageEdit"
          @fork="forkCurrentSession"
          @file="ElMessage.info(`预览产物文件: ${$event}`)"
          @resume="resumeSession"
        />

        <!-- ChatGPT 风格底部输入器 (带斜杠快捷菜单、停止/发送状态切换) -->
        <AgentComposer
          v-model:draft="draft"
          :running="isRunning"
          :commands="slashCommands"
          @send="handleSendMessage"
          @stop="stopGeneration(true)"
          @execute-command="handleExecuteCommand"
        />
      </main>
    </div>

    <!-- 3. 全局设置抽屉 -->
    <AgentGlobalSettingsModal
      v-model="showSettings"
      @changed="ElMessage.success('设置已同步')"
    />

    <!-- 4. 分支拓扑抽屉 -->
    <AgentBranchDrawer
      v-model:visible="showBranches"
      :sessions="mockSessions"
      :selected-session-id="currentSessionId"
      @select="selectSession"
      @fork="forkCurrentSession"
    />

    <!-- 5. 产物文件查看抽屉 -->
    <el-drawer v-model="showFiles" title="Agent 运行时产物与工作区" size="min(92vw, 680px)">
      <div class="file-demo-preview">
        <p class="text-sm text-muted">包含当前会话执行生成的分析报告、配置差分与转储快照：</p>
        <div class="mock-file-card">
          <AppIcon name="file" size="md" />
          <div>
            <strong>diffs/hikari-patch.diff</strong>
            <small>连接池配置增量热补丁 · 1.2 KB</small>
          </div>
          <el-button size="small" text>下载</el-button>
        </div>
        <div class="mock-file-card">
          <AppIcon name="file" size="md" />
          <div>
            <strong>summaries/turn-1-compacted.md</strong>
            <small>第 1 轮早期历史上下文摘要 · 8.4 KB</small>
          </div>
          <el-button size="small" text>预览</el-button>
        </div>
      </div>
    </el-drawer>

    <!-- 6. 工作流关联历史抽屉 -->
    <el-drawer v-model="showWorkflowDrawer" title="关联 Workflow 运行记录" size="min(92vw, 640px)">
      <div class="p-2">
        <p class="text-sm text-muted">选择已完成的工作流作为 Agent 分析的初始化上下文：</p>
        <div class="mock-wf-card">
          <strong>每日日志定时巡检 / wf-run-8821</strong>
          <span class="status-tag success">Completed</span>
          <p class="text-xs text-muted mt-1">触发于 2 小时前 · 发现 48 条告警日志</p>
          <el-button size="small" type="primary" class="mt-2" @click="ElMessage.success('已导入工作流基线')">
            以此结果创建会话
          </el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.chatgpt-demo-wrapper {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 84px);
}

.chatgpt-chat-container {
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
.chat-sidebar {
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
  background: var(--el-fill-color-light);
  overflow: hidden;
}

.sidebar-top {
  padding: 12px;
}

.new-chat-btn {
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

.new-chat-btn:hover {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary) 5%, var(--surface));
}

.sidebar-search {
  padding: 0 12px 10px;
}

.sidebar-sessions {
  flex: 1;
  overflow-y: auto;
  padding: 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.group-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
  letter-spacing: 0.04em;
  padding: 6px 8px 4px;
}

.session-nav-item {
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

.session-nav-item:hover {
  background: var(--surface);
  border-color: var(--border);
}

.session-nav-item.active {
  background: var(--surface);
  border-color: color-mix(in srgb, var(--el-color-primary) 40%, transparent);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
}

.session-nav-icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: var(--el-fill-color);
  color: var(--muted);
  flex-shrink: 0;
}

.session-nav-item.active .session-nav-icon {
  background: color-mix(in srgb, var(--el-color-primary) 12%, transparent);
  color: var(--el-color-primary);
}

.session-nav-meta {
  flex: 1;
  min-width: 0;
}

.session-nav-meta strong {
  display: block;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-nav-meta small {
  display: block;
  font-size: 11px;
  color: var(--muted);
  font-family: ui-monospace, monospace;
}

.session-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #cbd5e1;
}

.session-status-dot.running {
  background: #10b981;
  box-shadow: 0 0 6px #10b981;
}

.sidebar-footer {
  padding: 10px 12px;
  border-top: 1px solid var(--border);
}

.sidebar-footer-btn {
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

.sidebar-footer-btn:hover {
  background: var(--surface);
  color: var(--el-text-color-primary);
}

/* Main Column */
.chat-main-column {
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100%;
  background: var(--surface);
}

.mock-file-card,
.mock-wf-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  margin-top: 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--el-fill-color-light);
}

.mock-wf-card {
  flex-direction: column;
  align-items: flex-start;
}

@media (max-width: 768px) {
  .chatgpt-chat-container {
    grid-template-columns: 1fr;
  }
  .chat-sidebar {
    display: none;
  }
}
</style>
