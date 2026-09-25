<script setup lang="ts">
import type { useAgentFiles } from '../composables/useAgentFiles'

defineProps<{ files: ReturnType<typeof useAgentFiles> }>()
</script>
<template>
  <div class="file-browser">
    <div class="agent-file-toolbar">
      <el-input v-model="files.path.value" aria-label="文件路径" @keyup.enter="files.read()" />
      <el-button :loading="files.pending.value" @click="files.read()">读取</el-button>
      <el-button @click="files.createFile">新建文件</el-button>
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
        @click="files.openPath(entry)"
      >
        {{ entry }}
      </el-button>
    </div>
    <el-alert v-if="files.error.value" :title="files.error.value" type="error" :closable="false" />
    <el-alert v-if="files.notice.value" :title="files.notice.value" type="info" :closable="false" />
    <template v-if="files.page.value">
      <p v-if="files.page.value.readonly">运行时文件只读</p>
      <template v-if="files.page.value.kind === 'directory'">
        <button
          v-for="entry in files.page.value.entries"
          :key="entry.name"
          class="entry"
          @click="files.openEntry(entry.name)"
        >
          {{ entry.kind === 'directory' ? '目录' : '文件' }} · {{ entry.name }}
          {{ entry.readonly ? '· 只读' : '' }}
        </button>
      </template>
      <template v-else>
        <p class="version">
          {{ files.page.value.path }} · 版本 {{ files.version.value }} ·
          {{ files.page.value.total_lines ?? 0 }} 行 · 起始行
          {{ files.page.value.offset + 1 }}
        </p>
        <el-input
          v-model="files.draft.value"
          type="textarea"
          :rows="16"
          :readonly="!files.editable.value"
          aria-label="文件内容"
        />
        <el-button
          v-if="!files.complete.value && !files.page.value.readonly"
          @click="files.loadFull"
        >
          载入全文编辑
        </el-button>
        <el-button
          type="primary"
          :disabled="!files.editable.value || files.conflict.value"
          :loading="files.pending.value"
          @click="files.save"
        >
          保存
        </el-button>
      </template>
      <div class="pages">
        <el-button
          :disabled="files.page.value.offset === 0"
          @click="files.read(Math.max(0, files.page.value.offset - 200))"
        >
          上一页
        </el-button>
        <el-button
          :disabled="files.page.value.next_offset === null"
          @click="files.read(files.page.value.next_offset!)"
        >
          下一页
        </el-button>
      </div>
    </template>
    <section v-if="files.conflict.value || files.remote.value" aria-label="文件冲突合并">
      <p>文件冲突：草稿已保留。读取远端版本后手动合并。</p>
      <el-button @click="files.readRemote">读取最新版本（保留草稿）</el-button>
      <template v-if="files.remote.value">
        <pre>{{ files.remote.value.content }}</pre>
        <el-button @click="files.mergeRemote">使用最新版本继续合并</el-button>
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
