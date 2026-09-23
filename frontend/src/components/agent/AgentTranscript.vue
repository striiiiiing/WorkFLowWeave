<script setup lang="ts">
import { computed } from 'vue'
import type { AgentEvent, AgentTool } from '@/api/agents'
import ReportText from '@/components/report/ReportText.vue'
import AgentToolCall from './AgentToolCall.vue'
import { transcriptRows, type TranscriptRow } from './transcript'
const props = defineProps<{
  events: AgentEvent[]
  running: boolean
  sessionId: string
  tools?: AgentTool[]
}>()
const emit = defineEmits<{ edit: [event: AgentEvent]; file: [path: string] }>()
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
    )
      last.rows.push(row)
    else result.push({ key: row.key, rows: [row], read })
  }
  return result
})
</script>
<template>
  <section class="agent-messages" aria-live="polite" aria-label="Agent 对话">
    <template v-for="group in groups" :key="group.key">
      <details v-if="group.read" class="message read-group" open>
        <summary>读取工具组 · {{ group.rows.length }} 项（可并行）</summary>
        <AgentToolCall
          v-for="row in group.rows"
          :key="row.key"
          :row="row"
          :tool="tools?.find((tool) => tool.name === row.event.data.name)"
          @file="emit('file', $event)"
        />
      </details>
      <template v-else>
        <article
          v-for="row in group.rows"
          :key="row.key"
          class="message"
          :class="row.role"
          :data-event-id="row.event.id"
        >
          <template v-if="row.role === 'user'">
            <div class="message-label">
              用户
              <el-button
                v-if="row.event.session_id === sessionId && row.event.data.message_id"
                text
                size="small"
                :disabled="running"
                @click="emit('edit', row.event)"
              >
                编辑并创建分支
              </el-button>
            </div>
            <pre>{{ row.text }}</pre>
          </template>
          <template v-else-if="row.role === 'assistant'">
            <small>Agent</small>
            <ReportText :text="row.text" />
          </template>
          <AgentToolCall
            v-else-if="row.role === 'tool'"
            :row="row"
            :tool="tools?.find((tool) => tool.name === row.event.data.name)"
            @file="emit('file', $event)"
          />
          <template v-else-if="row.role === 'summary'">
            <strong>已压缩早期上下文 · 原始历史保留</strong>
            <small>事件范围 {{ JSON.stringify(row.event.data.source_event_range) }}</small>
            <ReportText :text="row.text" />
            <el-button
              v-if="row.event.data.artifact_path"
              text
              @click="emit('file', `Runtime/${row.event.data.artifact_path}`)"
            >
              查看摘要文件
            </el-button>
          </template>
          <template v-else-if="row.role === 'status'">
            <span>{{ row.text }} · {{ row.event.type }}</span>
            <pre v-if="row.event.data.error">{{
              JSON.stringify(row.event.data.error, null, 2)
            }}</pre>
            <p v-if="row.text === 'cancelled'">已停止。已经完成的写入和外部操作不会撤销。</p>
            <p v-if="row.text === 'interrupted'">运行已中断；未知副作用不会自动重做。</p>
          </template>
          <span v-else>{{ row.text }}</span>
        </article>
      </template>
    </template>
    <div v-if="!groups.length" class="agent-empty">发送第一条消息开始</div>
  </section>
</template>
<style scoped>
.agent-messages {
  overflow-y: auto;
  padding: 16px;
  min-height: 240px;
  flex: 1;
}
.agent-empty {
  display: grid;
  place-items: center;
  min-height: 180px;
  color: var(--el-text-color-secondary);
}
.message {
  padding: 12px;
  margin-bottom: 12px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  overflow-wrap: anywhere;
}
.message-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.user {
  background: color-mix(in srgb, var(--el-color-primary) 10%, transparent);
}
.summary {
  border-left: 3px solid var(--el-color-primary);
}
small {
  display: block;
  color: var(--el-text-color-secondary);
}
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font: inherit;
}
summary {
  cursor: pointer;
}
.status,
.command {
  font-size: 13px;
}
</style>
