<script setup lang="ts">
import { computed, ref } from 'vue'
import { sessionKind, sessionKindLabels } from '../model/session/sessionKind'
import type { AgentSession } from '../model/public'
import AppIcon from '@/shared/ui/icons/AppIcon.vue'

const props = defineProps<{ sessions: AgentSession[]; selectedId?: string }>()
const emit = defineEmits<{
  select: [session: AgentSession]
  branches: []
}>()
const search = ref('')
const kind = ref('all')
const visible = computed(() => {
  const query = search.value.trim().toLowerCase()
  const sessions = props.sessions.filter(
    (session) => kind.value === 'all' || sessionKind(session) === kind.value,
  )
  return query
    ? sessions.filter((session) =>
        [session.title ?? '', session.session_id, session.branch_id, session.model ?? ''].some(
          (value) => value.toLowerCase().includes(query),
        ),
      )
    : sessions
})
</script>

<template>
  <aside class="agent-sidebar">
    <el-input v-model="search" placeholder="搜索会话与分支" aria-label="搜索会话" clearable>
      <template #prefix><AppIcon name="search" size="sm" /></template>
    </el-input>
    <el-select v-model="kind" aria-label="会话类型">
      <el-option value="all" label="全部会话" />
      <el-option
        v-for="(label, value) in sessionKindLabels"
        :key="value"
        :value="value"
        :label="label"
      />
    </el-select>
    <nav aria-label="会话列表" class="agent-session-list">
      <button
        v-for="session in visible"
        :key="session.session_id"
        type="button"
        class="agent-session"
        :class="{ active: session.session_id === selectedId }"
        @click="emit('select', session)"
      >
        <AppIcon :name="session.parent_session_id ? 'fork' : 'bot'" size="sm" />
        <span>
          <strong>{{ session.title || session.branch_id || 'main' }}</strong>
          <small>
            {{ sessionKindLabels[sessionKind(session)] }}
            <template v-if="session.workflow_task_id">· {{ session.workflow_task_id }}</template>
          </small>
          <small>{{ session.session_id }}</small>
        </span>
        <i :class="session.status" />
      </button>
      <el-empty v-if="!visible.length" description="暂无会话" :image-size="48" />
    </nav>
    <div class="agent-sidebar-actions">
      <el-button text @click="emit('branches')">
        <AppIcon name="fork" size="sm" />
        分支树
      </el-button>
    </div>
  </aside>
</template>

<style scoped>
.agent-sidebar {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  padding: 12px;
  border-right: 1px solid var(--border);
  background: var(--el-fill-color-light);
}
.agent-session-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.agent-session {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 8px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.agent-session:hover,
.agent-session.active {
  background: var(--surface);
  border-color: var(--border);
}
.agent-session span {
  flex: 1;
  min-width: 0;
}
.agent-session strong,
.agent-session small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.agent-session small {
  color: var(--muted);
  font-size: 11px;
}
.agent-session i {
  width: 7px;
  height: 7px;
  flex: none;
  border-radius: 50%;
  background: #9ca3af;
}
.agent-session i.running {
  background: #059669;
}
.agent-sidebar-actions {
  display: flex;
  justify-content: space-between;
  border-top: 1px solid var(--border);
  padding-top: 8px;
}
</style>
