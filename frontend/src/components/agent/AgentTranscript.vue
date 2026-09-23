<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { AgentEvent, AgentTool } from '@/api/agents'
import ReportText from '@/components/report/ReportText.vue'
import AgentToolCall from './AgentToolCall.vue'
import { transcriptRows, type TranscriptRow } from './transcript'
import AppIcon from '@/components/icons/AppIcon.vue'
import { ElMessage } from 'element-plus'

const props = defineProps<{
  events: AgentEvent[]
  running: boolean
  sessionId: string
  tools?: AgentTool[]
}>()

const emit = defineEmits<{
  edit: [event: AgentEvent]
  fork: [event: AgentEvent]
  file: [path: string]
  resume: []
}>()

const copiedId = ref<string | null>(null)
const viewport = ref<HTMLElement>()
const following = ref(true)
let copyTimer: ReturnType<typeof setTimeout> | undefined
onBeforeUnmount(() => clearTimeout(copyTimer))

function trackScroll() {
  const el = viewport.value
  if (el) following.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}
async function scrollToLatest() {
  following.value = true
  await nextTick()
  const el = viewport.value
  if (el) el.scrollTop = el.scrollHeight
}
watch(
  () => props.events,
  () => {
    if (following.value) void scrollToLatest()
  },
  { deep: true },
)
watch(() => props.sessionId, scrollToLatest, { immediate: true })

const groups = computed(() => {
  const result: Array<{ key: string; rows: TranscriptRow[]; read: boolean }> = []
  for (const row of transcriptRows(props.events)) {
    const read = row.role === 'tool' && row.event.data.execution === 'read'
    const last = result[result.length - 1]
    if (
      read &&
      last?.read &&
      last.rows[0].event.turn_id === row.event.turn_id &&
      last.rows[0].group === row.group
    ) {
      last.rows.push(row)
    } else {
      result.push({ key: row.key, rows: [row], read })
    }
  }
  return result
})

async function copyText(text: string, id: string) {
  try {
    await navigator.clipboard.writeText(text)
    copiedId.value = id
    ElMessage.success('已复制到剪贴板')
    clearTimeout(copyTimer)
    copyTimer = setTimeout(() => {
      if (copiedId.value === id) copiedId.value = null
    }, 2000)
  } catch {
    ElMessage.error('复制失败，请选择消息文本后手动复制')
  }
}
</script>

<template>
  <section
    ref="viewport"
    class="transcript-viewport"
    aria-live="polite"
    aria-label="Agent 对话历史"
    @scroll="trackScroll"
  >
    <div class="transcript-stream">
      <template v-for="group in groups" :key="group.key">
        <!-- 1. 并发只读工具批次组 -->
        <details v-if="group.read" class="tool-read-group" open>
          <summary class="read-group-summary">
            <span class="group-icon">
              <AppIcon name="terminal" size="sm" />
            </span>
            <span class="group-label">并行只读工具组 · {{ group.rows.length }} 项</span>
            <span class="group-badge">Read Concurrency</span>
          </summary>
          <div class="read-group-calls">
            <AgentToolCall
              v-for="row in group.rows"
              :key="row.key"
              :row="row"
              :tool="tools?.find((tool) => tool.name === row.event.data.name)"
              @file="emit('file', $event)"
            />
          </div>
        </details>

        <!-- 2. 普通消息与单项处理 -->
        <template v-else>
          <div
            v-for="row in group.rows"
            :key="row.key"
            class="message-row"
            :class="`role-${row.role}`"
            :data-event-id="row.event.id"
          >
            <!-- 2.1 用户消息 -->
            <template v-if="row.role === 'user'">
              <div class="user-bubble-wrapper">
                <div class="user-bubble">
                  <div class="user-content">{{ row.text }}</div>
                  <div class="message-actions user-actions">
                    <button
                      type="button"
                      class="msg-act-btn"
                      title="复制内容"
                      @click="copyText(row.text, row.key)"
                    >
                      <AppIcon :name="copiedId === row.key ? 'check' : 'copy'" size="sm" />
                    </button>
                    <button
                      v-if="row.event.session_id === sessionId && row.event.data.message_id"
                      type="button"
                      class="msg-act-btn"
                      title="编辑并创建分支"
                      :disabled="running"
                      @click="emit('edit', row.event)"
                    >
                      <AppIcon name="fork" size="sm" />
                      <span>编辑并创建分支</span>
                    </button>
                  </div>
                </div>
              </div>
            </template>

            <!-- 2.2 Assistant 助手响应 -->
            <template v-else-if="row.role === 'assistant'">
              <div class="assistant-row">
                <div class="bot-avatar">
                  <AppIcon name="sparkles" size="sm" />
                </div>
                <div class="assistant-body">
                  <div class="assistant-content">
                    <ReportText :text="row.text" />
                  </div>
                  <div class="message-actions assistant-actions">
                    <button
                      type="button"
                      class="msg-act-btn"
                      title="复制回答"
                      @click="copyText(row.text, row.key)"
                    >
                      <AppIcon :name="copiedId === row.key ? 'check' : 'copy'" size="sm" />
                      <span>复制</span>
                    </button>
                    <button
                      type="button"
                      class="msg-act-btn"
                      title="以此节点创建独立分支"
                      :disabled="running"
                      @click="emit('fork', row.event)"
                    >
                      <AppIcon name="fork" size="sm" />
                      <span>创建分支</span>
                    </button>
                  </div>
                </div>
              </div>
            </template>

            <!-- 2.3 单项工具调用 (如工作区写锁/命令) -->
            <div v-else-if="row.role === 'tool'" class="single-tool-wrapper">
              <AgentToolCall
                :row="row"
                :tool="tools?.find((tool) => tool.name === row.event.data.name)"
                @file="emit('file', $event)"
              />
            </div>

            <!-- 2.4 上下文智能压缩里程碑卡片 (UI精心设计的压缩表现) -->
            <template v-else-if="row.role === 'summary'">
              <div class="compact-milestone-card">
                <div class="milestone-glow" />
                <div class="milestone-header">
                  <span class="milestone-badge">
                    <AppIcon name="archive" size="sm" />
                    <span>上下文智能精简已生效</span>
                  </span>
                  <span class="milestone-hint">
                    事件范围 {{ JSON.stringify(row.event.data.source_event_range) }}
                  </span>
                </div>
                <div class="milestone-summary">
                  <ReportText :text="row.text" />
                </div>
                <div v-if="row.event.data.artifact_path" class="milestone-actions">
                  <el-button
                    size="small"
                    text
                    @click="emit('file', `Runtime/${row.event.data.artifact_path}`)"
                  >
                    <AppIcon name="file" size="sm" />
                    <span>查看归档摘要文件</span>
                  </el-button>
                </div>
              </div>
            </template>

            <!-- 2.5 指令与系统状态卡片 (停止 / 中断 / 恢复) -->
            <template v-else-if="row.role === 'status'">
              <div class="status-banner" :class="row.text">
                <div class="status-icon">
                  <AppIcon :name="row.text === 'cancelled' ? 'pause' : 'activity'" size="sm" />
                </div>
                <div class="status-text">
                  <strong v-if="row.text === 'cancelled'">
                    会话已暂停 / 停止。已执行的文件变更与外部操作保持原样。
                  </strong>
                  <strong v-else-if="row.text === 'interrupted'">
                    会话已中断，未确定的副作用不会自动重试。
                  </strong>
                  <strong v-else>{{ row.text }} · {{ row.event.type }}</strong>
                  <pre v-if="row.event.data.error" class="error-detail">{{
                    JSON.stringify(row.event.data.error, null, 2)
                  }}</pre>
                </div>
              </div>
            </template>

            <!-- 2.6 命令排队与反馈 -->
            <div v-else-if="row.role === 'command'" class="command-pill">
              <AppIcon name="terminal" size="sm" />
              <span>{{ row.text }}</span>
            </div>
          </div>
        </template>
      </template>

      <!-- 思考中骨架指示器 (Streaming Shimmer) -->
      <div v-if="running" class="thinking-row">
        <div class="bot-avatar pulse">
          <AppIcon name="sparkles" size="sm" />
        </div>
        <div class="thinking-content">
          <div class="shimmer-line line-1" />
          <div class="shimmer-line line-2" />
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="!groups.length && !running" class="empty-transcript">
        <div class="empty-icon">
          <AppIcon name="bot" size="lg" />
        </div>
        <h3>开启 Agent 智能分析</h3>
        <p>
          输入你的业务目标或日志分析诉求，或在输入框输入
          <code>/</code>
          快速唤起指令。
        </p>
      </div>
    </div>
    <button v-if="!following" type="button" class="latest-message-btn" @click="scrollToLatest">
      回到最新消息
    </button>
  </section>
</template>

<style scoped>
.latest-message-btn {
  position: sticky;
  bottom: 8px;
  display: block;
  margin: 0 auto;
  padding: 6px 14px;
  border: 1px solid var(--border);
  border-radius: 20px;
  background: var(--surface);
  color: var(--el-color-primary);
  cursor: pointer;
}
.transcript-viewport {
  flex: 1;
  overflow-y: auto;
  padding: 20px 16px;
  scroll-behavior: smooth;
}

.transcript-stream {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 820px;
  margin: 0 auto;
  min-height: 100%;
}

/* User Message */
.user-bubble-wrapper {
  display: flex;
  justify-content: flex-end;
  margin: 4px 0;
}

.user-bubble {
  position: relative;
  max-width: 80%;
  padding: 10px 16px;
  border-radius: 18px 18px 4px 18px;
  background: color-mix(in srgb, var(--el-color-primary) 12%, var(--surface));
  border: 1px solid color-mix(in srgb, var(--el-color-primary) 22%, transparent);
  color: var(--el-text-color-primary);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.user-content {
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

/* Assistant Message */
.assistant-row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  margin: 4px 0;
}

.bot-avatar {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: var(--el-color-primary);
  color: #fff;
  flex-shrink: 0;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.25);
}

.bot-avatar.pulse {
  animation: avatarPulse 1.6s infinite ease-in-out;
}

@keyframes avatarPulse {
  0%,
  100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(0.92);
    opacity: 0.8;
  }
}

.assistant-body {
  flex: 1;
  min-width: 0;
}

.assistant-content {
  font-size: 14px;
  line-height: 1.7;
  color: var(--el-text-color-primary);
}

/* Message Actions */
.message-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  opacity: 0;
  transition: opacity 0.15s ease;
}

.message-row:hover .message-actions,
.user-bubble:hover .message-actions {
  opacity: 1;
}

.msg-act-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 6px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.12s ease;
}

.msg-act-btn:hover:not(:disabled) {
  background: var(--el-fill-color);
  color: var(--el-text-color-primary);
}

.msg-act-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Tool Calls & Groups */
.tool-read-group {
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--el-fill-color-light);
  overflow: hidden;
  margin: 6px 0;
}

.read-group-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  cursor: pointer;
  user-select: none;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}

.group-icon {
  color: var(--el-color-primary);
  display: grid;
  place-items: center;
}

.group-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.group-badge {
  font-size: 10px;
  font-family: ui-monospace, monospace;
  padding: 1px 6px;
  border-radius: 4px;
  background: #dbeafe;
  color: #1e40af;
  margin-left: auto;
}

.read-group-calls {
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.single-tool-wrapper {
  margin: 6px 0;
}

/* Compact Milestone Card */
.compact-milestone-card {
  position: relative;
  padding: 14px 18px;
  margin: 12px 0;
  border-radius: 12px;
  background: linear-gradient(
    135deg,
    color-mix(in srgb, var(--el-color-primary) 6%, var(--surface)),
    color-mix(in srgb, var(--el-color-primary) 2%, var(--surface))
  );
  border: 1px solid color-mix(in srgb, var(--el-color-primary) 25%, transparent);
  box-shadow: 0 2px 10px rgba(37, 99, 235, 0.05);
}

.milestone-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.milestone-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  color: var(--el-color-primary);
}

.milestone-hint {
  font-size: 11px;
  font-family: ui-monospace, monospace;
  color: var(--muted);
}

.milestone-summary {
  font-size: 13px;
  color: var(--el-text-color-regular);
  line-height: 1.6;
}

.milestone-actions {
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px dashed color-mix(in srgb, var(--border) 80%, transparent);
}

/* Status Banner */
.status-banner {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 12px 16px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid var(--border);
  color: var(--muted);
  font-size: 13px;
}

.status-banner.cancelled {
  background: #fffbeb;
  border-color: #fde68a;
  color: #92400e;
}

.status-banner.interrupted {
  background: #fef2f2;
  border-color: #fecaca;
  color: #991b1b;
}

.status-icon {
  margin-top: 2px;
  flex-shrink: 0;
}

.error-detail {
  margin-top: 6px;
  font-size: 11px;
  background: rgba(0, 0, 0, 0.04);
  padding: 6px;
  border-radius: 4px;
}

.command-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 12px;
  background: var(--el-fill-color-light);
  font-size: 11px;
  font-family: ui-monospace, monospace;
  color: var(--muted);
  align-self: center;
}

/* Thinking Indicator */
.thinking-row {
  display: flex;
  gap: 12px;
  align-items: center;
  margin: 8px 0;
}

.thinking-content {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 180px;
}

.shimmer-line {
  height: 10px;
  border-radius: 5px;
  background: linear-gradient(90deg, #f1f5f9 25%, #e2e8f0 50%, #f1f5f9 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
}

.shimmer-line.line-2 {
  width: 60%;
}

@keyframes shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

/* Empty State */
.empty-transcript {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  min-height: 320px;
  color: var(--muted);
}

.empty-icon {
  display: grid;
  place-items: center;
  width: 64px;
  height: 64px;
  border-radius: 20px;
  background: color-mix(in srgb, var(--el-color-primary) 10%, var(--surface));
  color: var(--el-color-primary);
  margin-bottom: 16px;
}

.empty-transcript h3 {
  font-size: 18px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin: 0 0 6px;
}

.empty-transcript p {
  font-size: 13px;
  max-width: 360px;
  line-height: 1.6;
  margin: 0;
}

.empty-transcript code {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--el-fill-color);
  font-family: ui-monospace, monospace;
}

:global(.dark) .user-bubble {
  background: #1e3a8a;
  border-color: #2563eb;
  color: #eff6ff;
}

:global(.dark) .tool-read-group {
  background: #0f172a;
  border-color: #334155;
}

:global(.dark) .read-group-summary {
  background: #1e293b;
  border-color: #334155;
}

:global(.dark) .group-badge {
  background: #172554;
  color: #93c5fd;
}

:global(.dark) .compact-milestone-card {
  background: #111e38;
  border-color: #1d4ed8;
}

:global(.dark) .status-banner.cancelled {
  background: #451a03;
  border-color: #78350f;
  color: #fde68a;
}

:global(.dark) .status-banner.interrupted {
  background: #450a0a;
  border-color: #7f1d1d;
  color: #fca5a5;
}
</style>
