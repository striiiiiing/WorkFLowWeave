<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { agentsApi, type AgentEvent, type AgentFile, type AgentSession } from '@/api/agents'
import { errorMessage } from '@/api/client'
import AppIcon from '@/components/icons/AppIcon.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import ReportText from '@/components/report/ReportText.vue'

const sessions = ref<AgentSession[]>([])
const selected = ref<AgentSession | null>(null)
const events = ref<AgentEvent[]>([])
const draft = ref('')
const loading = ref(false)
const error = ref('')
const tools = ref<Awaited<ReturnType<typeof agentsApi.tools>>>([])
const showTools = ref(false)
const showSettings = ref(false)
const showFiles = ref(false)
const filePath = ref('AGENTS.md')
const fileDraft = ref('')
const fileHash = ref<string | undefined>()
const fileReadOnly = ref(false)
const fileLoading = ref(false)
const commandMode = ref<'send' | 'append'>('send')
const agentConfig = ref<Awaited<ReturnType<typeof agentsApi.config>> | null>(null)
let stream: EventSource | undefined
let lastEventId = 0
let expectedStreamClose = false

const messages = computed(() => events.value.filter((event) =>
  ['message.user', 'message.delta', 'message.completed', 'turn.completed', 'turn.failed',
    'turn.cancelled', 'turn.interrupted', 'context.compacted', 'tool.queued',
    'tool.started', 'tool.completed', 'tool.outcome_unknown'].includes(event.type),
))

async function refresh() {
  try {
    sessions.value = await agentsApi.list()
    if (!selected.value && sessions.value[0]) await select(sessions.value[0])
  } catch (err) {
    error.value = errorMessage(err)
  }
}
async function create() {
  try {
    await select(await agentsApi.create({}))
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}
async function fork() {
  if (!selected.value) return
  try {
    await select(await agentsApi.fork(selected.value.session_id))
    await refresh()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}
async function select(session: AgentSession) {
  selected.value = session
  events.value = []
  expectedStreamClose = true
  stream?.close()
  lastEventId = 0
  expectedStreamClose = false
  stream = new EventSource(`/api/agents/sessions/${encodeURIComponent(session.session_id)}/events?after=${lastEventId}`)
  stream.onmessage = (event) => {
    const value = JSON.parse(event.data) as AgentEvent
    lastEventId = Math.max(lastEventId, value.id)
    if (!events.value.some((item) => item.id === value.id)) events.value.push(value)
    if (['turn.completed', 'turn.failed', 'turn.cancelled', 'turn.interrupted'].includes(value.type)) {
      void refresh()
      expectedStreamClose = true
      stream?.close()
      stream = undefined
    }
  }
  stream.onerror = () => {
    stream?.close()
    stream = undefined
    if (expectedStreamClose) return
    if (selected.value?.session_id === session.session_id) {
      window.setTimeout(() => {
        if (selected.value?.session_id === session.session_id) {
          stream = new EventSource(`/api/agents/sessions/${encodeURIComponent(session.session_id)}/events?after=${lastEventId}`)
          stream.onmessage = (event) => {
            const value = JSON.parse(event.data) as AgentEvent
            lastEventId = Math.max(lastEventId, value.id)
            if (!events.value.some((item) => item.id === value.id)) events.value.push(value)
            if (['turn.completed', 'turn.failed', 'turn.cancelled', 'turn.interrupted'].includes(value.type)) {
              expectedStreamClose = true
              stream?.close()
              stream = undefined
            }
          }
        }
      }, 500)
    }
  }
}
async function send() {
  if (!selected.value || !draft.value.trim() || loading.value) return
  loading.value = true
  const text = draft.value.trim()
  draft.value = ''
  try {
    const requestId = crypto.randomUUID()
    if (commandMode.value === 'append') {
      await agentsApi.append(selected.value.session_id, requestId, text)
    } else {
      await agentsApi.send(selected.value.session_id, requestId, text)
    }
  } catch (err) {
    draft.value = text
    ElMessage.error(errorMessage(err))
  } finally {
    loading.value = false
  }
}
async function loadFile() {
  if (!selected.value || !filePath.value.trim()) return
  fileLoading.value = true
  try {
    const result = await agentsApi.readFile(selected.value.session_id, filePath.value) as AgentFile
    fileDraft.value = typeof result.content === 'string' ? result.content : JSON.stringify(result, null, 2)
    fileHash.value = typeof result.hash === 'string' ? result.hash : undefined
    fileReadOnly.value = filePath.value.startsWith('Runtime/')
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    fileLoading.value = false
  }
}
async function saveFile() {
  if (!selected.value || fileReadOnly.value) return
  try {
    const result = await agentsApi.writeFile(
      selected.value.session_id, filePath.value,
      { mode: 'overwrite', content: fileDraft.value }, fileHash.value,
    )
    fileHash.value = typeof result.hash === 'string' ? result.hash : fileHash.value
    ElMessage.success('文件已保存，下一轮生效')
  } catch (err) {
    // Keep the draft in place on conflict so the user can reload or merge it.
    ElMessage.error(errorMessage(err))
  }
}
async function cancel() {
  if (!selected.value) return
  await agentsApi.cancel(selected.value.session_id)
}
async function compact() {
  if (!selected.value) return
  try {
    await agentsApi.compact(selected.value.session_id)
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}
async function loadTools() {
  try {
    tools.value = await agentsApi.tools()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}
async function loadConfig() {
  try {
    agentConfig.value = await agentsApi.config()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}
async function toggleTool(plugin: string, enabled: boolean) {
  try {
    await agentsApi.updateTool(plugin, enabled)
    await loadTools()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}
function eventText(event: AgentEvent): string {
  if (typeof event.text === 'string') return event.text
  if (typeof event.content === 'string') return event.content
  if (typeof event.error === 'object' && event.error !== null) return JSON.stringify(event.error)
  return ''
}
function eventRole(event: AgentEvent): string {
  if (event.type === 'message.user') return 'user'
  if (event.type.startsWith('tool.')) return 'tool'
  if (event.type === 'context.compacted') return 'compacted'
  if (event.type.startsWith('turn.')) return 'status'
  return 'assistant'
}
void refresh()
onBeforeUnmount(() => stream?.close())
</script>

<template>
  <div class="agent-shell">
    <aside class="agent-sessions">
      <PageHeader title="Agent 会话" description="文件优先的多轮分析入口">
        <el-button type="primary" @click="create"><AppIcon name="plus" />新会话</el-button>
      </PageHeader>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <button
        v-for="session in sessions"
        :key="session.session_id"
        class="agent-session-row"
        :class="{ active: selected?.session_id === session.session_id }"
        @click="select(session)"
      >
        <strong>{{ session.session_id.slice(0, 12) }}</strong>
        <span class="muted">{{ session.status }}</span>
      </button>
    </aside>
    <main class="agent-conversation">
      <div v-if="!selected" class="agent-empty">选择或创建一个会话</div>
      <template v-else>
        <header class="agent-toolbar">
          <div><strong>{{ selected.session_id }}</strong><span class="muted"> · {{ selected.status }}</span></div>
          <div class="agent-actions">
            <el-button text @click="showTools = !showTools; showTools && loadTools()">工具</el-button>
            <el-button text @click="showFiles = !showFiles; showFiles && loadFile()">文件</el-button>
            <el-button text @click="showSettings = !showSettings; showSettings && loadConfig()">设置</el-button>
            <el-button text @click="fork">分支</el-button>
            <el-button text :disabled="selected.status === 'running'" @click="compact">压缩</el-button>
            <el-button text :disabled="selected.status !== 'running'" @click="cancel"><AppIcon name="square" />停止</el-button>
          </div>
        </header>
        <section class="agent-messages" aria-live="polite">
          <article v-for="message in messages" :key="message.id" class="agent-message" :class="`agent-message-${eventRole(message)}`">
            <span class="muted">{{ eventRole(message) }} · {{ message.type }}</span>
            <ReportText v-if="eventRole(message) === 'assistant' && eventText(message)" :text="eventText(message)" />
            <pre v-else-if="eventText(message)">{{ eventText(message) }}</pre>
          </article>
          <div v-if="!messages.length" class="agent-empty">发送第一条消息开始</div>
        </section>
        <form class="agent-composer" @submit.prevent="send">
          <el-input v-model="draft" type="textarea" :rows="3" aria-label="Agent 消息" placeholder="询问日志、分析结果或工作区文件" />
          <div class="agent-compose-actions">
            <el-button text @click="commandMode = commandMode === 'send' ? 'append' : 'send'">
              {{ commandMode === 'append' ? '追加到当前轮后' : '新轮次' }}
            </el-button>
            <el-button type="primary" native-type="submit" :loading="loading" :disabled="!draft.trim()"><AppIcon name="send" />发送</el-button>
          </div>
        </form>
        <aside v-if="showTools" class="agent-tools" aria-label="Agent 工具">
          <strong>当前工具</strong>
          <div v-for="tool in tools" :key="tool.name" class="agent-tool-row">
            <span>{{ tool.name }} <small class="muted">{{ tool.plugin ?? '' }}</small></span>
            <span class="agent-tool-meta">
              <span class="muted">{{ tool.execution }} · gen {{ tool.generation ?? '?' }} · ~{{ tool.definition_tokens ?? '?' }} tokens</span>
              <el-switch
                v-if="tool.plugin"
                :model-value="tool.enabled"
                :aria-label="`切换 ${tool.name}`"
                @change="(value) => toggleTool(tool.plugin!, Boolean(value))"
              />
            </span>
          </div>
        </aside>
        <aside v-if="showFiles" class="agent-files" aria-label="Agent 文件">
          <div class="agent-file-toolbar">
            <el-input v-model="filePath" size="small" placeholder="AGENTS.md / Memory/..." @keyup.enter="loadFile" />
            <el-button size="small" :loading="fileLoading" @click="loadFile">读取</el-button>
            <el-button size="small" type="primary" :disabled="fileReadOnly" @click="saveFile">保存</el-button>
          </div>
          <el-alert v-if="fileReadOnly" title="Runtime 文件只读" type="info" :closable="false" />
          <el-input v-model="fileDraft" type="textarea" :rows="8" :readonly="fileReadOnly" aria-label="文件内容" />
          <span class="muted">保存携带当前版本；冲突时保留草稿，可重新读取后合并。</span>
        </aside>
        <aside v-if="showSettings" class="agent-settings" aria-label="Agent 设置">
          <template v-if="agentConfig">
            <span>沙箱：{{ agentConfig.sandbox.status }} · 网络{{ agentConfig.sandbox.network ? '开启' : '关闭' }}</span>
            <span>并发：读 {{ agentConfig.scheduler.reading ?? 0 }}/{{ agentConfig.scheduler.read_concurrency ?? '?' }} · 写 {{ agentConfig.scheduler.writing ?? 0 }}/1 · 排队 {{ agentConfig.scheduler.queued ?? 0 }}</span>
            <span>上下文窗口：{{ agentConfig.config.context_window ?? '未配置' }} · 输出预留 {{ agentConfig.config.output_tokens ?? '默认' }}</span>
          </template>
          <span v-else class="muted">正在读取设置</span>
        </aside>
      </template>
    </main>
  </div>
</template>

<style scoped>
.agent-actions { display: flex; gap: 4px; }
.agent-compose-actions, .agent-tool-meta, .agent-file-toolbar { display: flex; align-items: center; gap: 8px; }
.agent-message-user { background: color-mix(in srgb, var(--el-color-primary) 10%, transparent); }
.agent-message-compacted { border-left: 3px solid var(--el-color-primary); }
.agent-tools { padding: 12px 16px; border-top: 1px solid var(--border); }
.agent-tool-row { display: flex; justify-content: space-between; gap: 8px; padding: 6px 0; }
.agent-files { padding: 12px 16px; border-top: 1px solid var(--border); display: grid; gap: 8px; }
.agent-settings { padding: 12px 16px; border-top: 1px solid var(--border); display: grid; gap: 4px; }
.agent-file-toolbar :deep(.el-input) { flex: 1; }
@media (max-width: 720px) {
  .agent-shell { display: block; }
  .agent-sessions { margin-bottom: 12px; }
  .agent-toolbar { align-items: flex-start; flex-direction: column; }
  .agent-composer { flex-direction: column; align-items: stretch; }
  .agent-compose-actions { justify-content: space-between; }
  .agent-tool-meta { align-items: flex-end; flex-direction: column; }
}
</style>
