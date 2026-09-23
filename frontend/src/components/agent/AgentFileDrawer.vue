<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { agentsApi, type AgentFile } from '@/api/agents'
import { ApiError } from '@/api/client'
import { useAsyncTask } from '@/composables/useAsyncTask'
const props = defineProps<{ sessionId: string; initialPath: string }>()
const task = useAsyncTask()
const path = ref(props.initialPath)
const page = ref<AgentFile>()
const draft = ref('')
const complete = ref(false)
const version = ref('')
const conflict = ref(false)
const remote = ref<AgentFile>()
const notice = ref('')
const editable = computed(
  () => page.value?.kind === 'file' && !page.value.readonly && complete.value,
)
async function read(offset = 0) {
  await task.run(async () => {
    const result = await agentsApi.readFile(props.sessionId, path.value, offset)
    page.value = result
    draft.value = result.content ?? ''
    version.value = result.hash ?? ''
    complete.value = offset === 0 && result.next_offset === null
    conflict.value = false
    remote.value = undefined
    notice.value = ''
  })
}
async function wholeFile(): Promise<AgentFile> {
  const filePath = page.value?.path ?? path.value
  let result = await agentsApi.readFile(props.sessionId, filePath)
  const first = result
  let content = result.content ?? ''
  while (result.next_offset !== null) {
    result = await agentsApi.readFile(props.sessionId, filePath, result.next_offset)
    if (result.hash !== first.hash) throw new Error('读取期间文件发生变化，请重新载入')
    content += result.content ?? ''
  }
  return { ...first, content, next_offset: null }
}
function loadFull() {
  void task.run(async () => {
    const result = await wholeFile()
    page.value = result
    draft.value = result.content ?? ''
    version.value = result.hash ?? ''
    complete.value = true
  })
}
function save() {
  void task.run(async () => {
    try {
      const result = await agentsApi.writeFile(
        props.sessionId,
        page.value!.path,
        draft.value,
        version.value,
      )
      version.value = result.hash
      conflict.value = false
      remote.value = undefined
      notice.value = '文件已保存，下一轮生效'
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) conflict.value = true
      throw cause
    }
  })
}
function readRemote() {
  void task.run(async () => {
    remote.value = await wholeFile()
  })
}
function mergeRemote() {
  if (!remote.value?.hash) return
  version.value = remote.value.hash
  conflict.value = false
  task.error.value = ''
  notice.value = '已采用最新版本号；草稿已保留，请合并后保存'
}
function createFile() {
  page.value = { path: path.value, kind: 'file', readonly: false, offset: 0, next_offset: null }
  draft.value = ''
  version.value = '*'
  complete.value = true
  conflict.value = false
  notice.value = '新文件使用不存在条件创建；已有文件不会被覆盖'
}
function openEntry(name: string) {
  path.value = `${path.value === '.' ? '' : path.value + '/'}${name}`
  void read()
}
function openPath(value: string) {
  path.value = value
  void read()
}
watch(
  () => [props.initialPath, props.sessionId],
  () => {
    path.value = props.initialPath
    void read()
  },
  { immediate: true },
)
</script>
<template>
  <div class="file-browser">
    <div class="agent-file-toolbar">
      <el-input v-model="path" aria-label="文件路径" @keyup.enter="read()" />
      <el-button :loading="task.pending.value" @click="read()">读取</el-button>
      <el-button @click="createFile">新建文件</el-button>
    </div>
    <div class="shortcuts">
      <el-button
        v-for="entry in [
          '.',
          'AGENTS.md',
          'Memory',
          'History',
          'Runtime/self.json',
          'Runtime/Sessions',
          'Runtime/History',
          'Runtime/Artifacts',
          'Runtime/Catalog',
        ]"
        :key="entry"
        text
        @click="openPath(entry)"
      >
        {{ entry }}
      </el-button>
    </div>
    <el-alert v-if="task.error.value" :title="task.error.value" type="error" :closable="false" />
    <el-alert v-if="notice" :title="notice" type="info" :closable="false" />
    <template v-if="page">
      <p v-if="page.readonly">运行时文件只读</p>
      <template v-if="page.kind === 'directory'">
        <button
          v-for="entry in page.entries"
          :key="entry.name"
          class="entry"
          @click="openEntry(entry.name)"
        >
          {{ entry.kind === 'directory' ? '目录' : '文件' }} · {{ entry.name }}
          {{ entry.readonly ? '· 只读' : '' }}
        </button>
      </template>
      <template v-else>
        <p class="version">
          {{ page.path }} · 版本 {{ version }} · {{ page.total_lines ?? 0 }} 行 · 起始行
          {{ page.offset + 1 }}
        </p>
        <el-input
          v-model="draft"
          type="textarea"
          :rows="16"
          :readonly="!editable"
          aria-label="文件内容"
        />
        <el-button v-if="!complete && !page.readonly" @click="loadFull">载入全文编辑</el-button>
        <el-button
          type="primary"
          :disabled="!editable || conflict"
          :loading="task.pending.value"
          @click="save"
        >
          保存
        </el-button>
      </template>
      <div class="pages">
        <el-button :disabled="page.offset === 0" @click="read(Math.max(0, page.offset - 200))">
          上一页
        </el-button>
        <el-button :disabled="page.next_offset === null" @click="read(page.next_offset!)">
          下一页
        </el-button>
      </div>
    </template>
    <section v-if="conflict || remote" aria-label="文件冲突合并">
      <p>文件冲突：草稿已保留。读取远端版本后手动合并。</p>
      <el-button @click="readRemote">读取最新版本（保留草稿）</el-button>
      <template v-if="remote">
        <pre>{{ remote.content }}</pre>
        <el-button @click="mergeRemote">使用最新版本继续合并</el-button>
      </template>
    </section>
  </div>
</template>
<style scoped>
.file-browser {
  display: grid;
  gap: 12px;
}
.agent-file-toolbar,
.shortcuts,
.pages {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.agent-file-toolbar .el-input {
  flex: 1;
  min-width: 160px;
}
.version,
pre {
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  font-size: 12px;
}
.entry {
  text-align: left;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
</style>
