<script setup lang="ts">
import { computed } from 'vue'
import type { AgentSession } from '@/api/agents'
const props = defineProps<{ sessions: AgentSession[]; selected?: string }>()
const emit = defineEmits<{ select: [session: AgentSession] }>()
const rows = computed(() => {
  const result: Array<{ session: AgentSession; depth: number }> = []
  const seen = new Set<string>()
  function visit(session: AgentSession, depth: number) {
    if (seen.has(session.session_id)) return
    seen.add(session.session_id)
    result.push({ session, depth })
    props.sessions
      .filter((item) => item.parent_session_id === session.session_id)
      .forEach((child) => visit(child, depth + 1))
  }
  props.sessions.filter((item) => !item.parent_session_id).forEach((item) => visit(item, 0))
  props.sessions.forEach((item) => visit(item, 0))
  return result
})
</script>
<template>
  <nav aria-label="会话分支树" class="branch-tree">
    <button
      v-for="row in rows"
      :key="row.session.session_id"
      :aria-current="selected === row.session.session_id ? 'page' : undefined"
      :style="{ paddingLeft: `${12 + Math.min(row.depth, 6) * 14}px` }"
      @click="emit('select', row.session)"
    >
      <strong>{{ row.depth ? '↳ ' : '' }}{{ row.session.session_id.slice(0, 14) }}</strong>
      <small>{{ row.session.branch_id }} · {{ row.session.status }}</small>
      <small v-if="row.session.parent_branch_id">父分支 {{ row.session.parent_branch_id }}</small>
    </button>
  </nav>
</template>
<style scoped>
.branch-tree {
  display: grid;
  gap: 6px;
}
button {
  text-align: left;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: transparent;
  color: inherit;
  padding: 10px;
  cursor: pointer;
  overflow-wrap: anywhere;
}
button[aria-current] {
  border-color: var(--el-color-primary);
  background: var(--el-fill-color-light);
}
small {
  display: block;
  color: var(--el-text-color-secondary);
}
</style>
