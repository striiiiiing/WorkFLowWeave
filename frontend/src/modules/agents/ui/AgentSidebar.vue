<script setup lang="ts">
import { computed, ref } from 'vue'
import type { AgentSession } from '../model/types'
import AppIcon from '@/shared/ui/icons/AppIcon.vue'

const props = defineProps<{ sessions: AgentSession[]; selectedId?: string; pending?: boolean }>()
const emit = defineEmits<{
  select: [session: AgentSession]
  create: []
  branches: []
  settings: []
}>()
const search = ref('')
const visible = computed(() => {
  const query = search.value.trim().toLowerCase()
  return query
    ? props.sessions.filter((session) =>
        [session.session_id, session.branch_id, session.model ?? ''].some((value) =>
          value.toLowerCase().includes(query),
        ),
      )
    : props.sessions
})
</script>

<template>
  <aside class="agent-sidebar">
    <el-button type="primary" :loading="pending" @click="emit('create')">
      <AppIcon name="plus" size="sm" />
      新会话
    </el-button>
    <el-input v-model="search" placeholder="搜索会话与分支" aria-label="搜索会话" clearable>
      <template #prefix><AppIcon name="search" size="sm" /></template>
    </el-input>
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
          <strong>{{ session.branch_id || 'main' }}</strong>
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
      <el-button text @click="emit('settings')">
        <AppIcon name="settings" size="sm" />
        设置
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
