<script setup lang="ts">
import { computed } from 'vue'
import type { AgentTool } from '../model/public'
import type { TranscriptRow } from '../model/runtime/transcript'
const props = defineProps<{ row: TranscriptRow; tool?: AgentTool }>()
const emit = defineEmits<{ file: [path: string] }>()
const result = computed(() => props.row.event.data.result as Record<string, unknown> | undefined)
const argumentsValue = computed(
  () => props.row.event.data.arguments as Record<string, unknown> | undefined,
)
const actualTool = computed(() => {
  if (props.row.event.data.name !== 'mcp') return String(props.row.event.data.name ?? '工具')
  const server = argumentsValue.value?.server
  const tool = argumentsValue.value?.tool
  return server && tool ? `MCP ${server} / ${tool}` : 'MCP'
})
const artifact = computed(() =>
  String(props.row.event.data.artifact_path ?? result.value?.artifact_path ?? ''),
)
</script>
<template>
  <details class="tool-call">
    <summary>
      {{ actualTool }}
      <span v-if="argumentsValue?.target">· {{ argumentsValue.target }}</span>
      · {{ row.status }}
      <span v-if="row.event.data.execution === 'exclusive'">
        · 工作区独占{{ row.status === '排队' ? '等待' : '' }}
      </span>
    </summary>
    <p v-if="result?.duration_ms !== undefined">耗时 {{ result.duration_ms }} ms</p>
    <p v-if="result?.truncated">显示截断预览；完整结果保存在 Artifact。</p>
    <strong>参数</strong>
    <pre>{{ JSON.stringify(argumentsValue, null, 2) }}</pre>
    <strong>结果 / 诊断</strong>
    <pre>{{ JSON.stringify(result, null, 2) }}</pre>
    <details v-if="tool?.input_schema">
      <summary>工具 Schema（当前设置代次 {{ tool.generation }}）</summary>
      <pre>{{ JSON.stringify(tool.input_schema, null, 2) }}</pre>
    </details>
    <el-button v-if="artifact" text @click="emit('file', `Runtime/${artifact}`)">
      读取完整输出
    </el-button>
  </details>
</template>
<style scoped>
.tool-call {
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  margin: 6px 0;
}
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 12px;
}
summary {
  cursor: pointer;
  overflow-wrap: anywhere;
}
</style>
