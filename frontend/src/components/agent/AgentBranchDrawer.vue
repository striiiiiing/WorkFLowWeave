<script setup lang="ts">
import { computed } from 'vue'
import type { AgentSession } from '@/api/agents'
import AppIcon from '@/components/icons/AppIcon.vue'

const props = defineProps<{
  visible: boolean
  sessions: AgentSession[]
  selectedSessionId?: string
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  select: [session: AgentSession]
  fork: [session: AgentSession]
}>()

interface BranchNode {
  session: AgentSession
  depth: number
  isRoot: boolean
  hasChildren: boolean
}

const tree = computed(() => {
  const result: BranchNode[] = []
  const seen = new Set<string>()

  // Map of children
  const childrenMap = new Map<string, AgentSession[]>()
  for (const s of props.sessions) {
    if (s.parent_session_id) {
      const list = childrenMap.get(s.parent_session_id) ?? []
      list.push(s)
      childrenMap.set(s.parent_session_id, list)
    }
  }

  function walk(session: AgentSession, depth: number) {
    if (seen.has(session.session_id)) return
    seen.add(session.session_id)

    const children = childrenMap.get(session.session_id) ?? []
    result.push({
      session,
      depth,
      isRoot: !session.parent_session_id,
      hasChildren: children.length > 0,
    })

    for (const child of children) {
      walk(child, depth + 1)
    }
  }

  // First process roots
  props.sessions
    .filter((s) => !s.parent_session_id)
    .forEach((s) => walk(s, 0))

  // In case of disconnected branches
  props.sessions.forEach((s) => walk(s, 0))

  return result
})

function formatTime(iso: string) {
  try {
    const d = new Date(iso)
    return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
  } catch {
    return iso
  }
}
</script>

<template>
  <el-drawer
    :model-value="visible"
    title="会话分支与执行图谱"
    size="min(92vw, 420px)"
    direction="rtl"
    class="branch-drawer"
    @update:model-value="emit('update:visible', $event)"
  >
    <div class="branch-drawer-header">
      <div class="branch-icon">
        <AppIcon name="fork" size="md" />
      </div>
      <div>
        <strong>版本控制与分支衍生</strong>
        <p>支持从任意检查点或历史消息派生分支，探索不同分析方向与排查策略。</p>
      </div>
    </div>

    <div class="branch-tree-container">
      <div
        v-for="node in tree"
        :key="node.session.session_id"
        class="tree-node"
        :class="{
          active: selectedSessionId === node.session.session_id,
          child: node.depth > 0,
        }"
        :style="{ '--depth': node.depth }"
      >
        <div class="node-rail">
          <div v-if="node.depth > 0" class="rail-elbow" />
          <div
            class="rail-dot"
            :class="{
              selected: selectedSessionId === node.session.session_id,
              running: node.session.status === 'running',
            }"
          >
            <AppIcon v-if="selectedSessionId === node.session.session_id" name="check" size="sm" />
          </div>
          <div v-if="node.hasChildren" class="rail-line" />
        </div>

        <div
          class="node-card"
          :class="{ current: selectedSessionId === node.session.session_id }"
          @click="emit('select', node.session)"
        >
          <div class="card-header">
            <span class="branch-name">
              <AppIcon name="fork" size="sm" />
              <strong>{{ node.session.branch_id || 'main' }}</strong>
            </span>
            <span class="status-pill" :class="node.session.status">
              {{ node.session.status }}
            </span>
          </div>

          <div class="card-meta">
            <span class="session-id">{{ node.session.session_id.slice(0, 16) }}...</span>
            <span v-if="node.session.created_at" class="timestamp">
              {{ formatTime(node.session.created_at) }}
            </span>
          </div>

          <div v-if="node.session.model" class="model-tag">
            <AppIcon name="bot" size="sm" />
            <span>{{ node.session.model }}</span>
          </div>

          <div class="card-actions" @click.stop>
            <el-button
              v-if="selectedSessionId !== node.session.session_id"
              size="small"
              text
              @click="emit('select', node.session)"
            >
              切换至此分支
            </el-button>
            <el-button
              size="small"
              text
              type="primary"
              :disabled="!node.session.continuable"
              @click="emit('fork', node.session)"
            >
              <AppIcon name="fork" size="sm" />
              <span>以此派生新分支</span>
            </el-button>
          </div>
        </div>
      </div>

      <el-empty v-if="!tree.length" description="暂无分支记录" />
    </div>
  </el-drawer>
</template>

<style scoped>
.branch-drawer-header {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 12px 14px;
  margin-bottom: 16px;
  background: color-mix(in srgb, var(--el-color-primary) 8%, var(--surface));
  border: 1px solid color-mix(in srgb, var(--el-color-primary) 18%, transparent);
  border-radius: 8px;
}

.branch-icon {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--el-color-primary) 15%, transparent);
  color: var(--el-color-primary);
  flex-shrink: 0;
}

.branch-drawer-header strong {
  display: block;
  font-size: 13px;
  color: var(--el-text-color-primary);
}

.branch-drawer-header p {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.4;
}

.branch-tree-container {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 4px;
}

.tree-node {
  display: flex;
  gap: 12px;
  position: relative;
  padding-left: calc(var(--depth) * 20px);
}

.node-rail {
  position: relative;
  width: 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  flex-shrink: 0;
}

.rail-dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid var(--border);
  background: var(--surface);
  margin-top: 14px;
  z-index: 2;
  display: grid;
  place-items: center;
  transition: all 0.2s ease;
}

.rail-dot.selected {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary);
  color: #fff;
}

.rail-dot.running {
  border-color: #10b981;
  background: #10b981;
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0% {
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.4);
  }
  70% {
    box-shadow: 0 0 0 8px rgba(16, 185, 129, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
  }
}

.rail-elbow {
  position: absolute;
  top: 0;
  left: -10px;
  width: 20px;
  height: 20px;
  border-bottom: 2px dashed var(--border);
  border-left: 2px dashed var(--border);
  border-bottom-left-radius: 8px;
}

.rail-line {
  position: absolute;
  top: 28px;
  bottom: -16px;
  width: 2px;
  background: var(--border);
}

.node-card {
  flex: 1;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
  cursor: pointer;
  transition: all 0.15s ease;
}

.node-card:hover {
  border-color: color-mix(in srgb, var(--el-color-primary) 35%, transparent);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.node-card.current {
  border-color: var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary) 5%, var(--surface));
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.branch-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--el-text-color-primary);
}

.status-pill {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
  text-transform: capitalize;
}

.status-pill.completed {
  background: #dcfce7;
  color: #15803d;
}

.status-pill.running {
  background: #dbeafe;
  color: #1d4ed8;
}

.status-pill.interrupted,
.status-pill.failed {
  background: #fee2e2;
  color: #b91c1c;
}

.card-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
  font-size: 11px;
  color: var(--muted);
  font-family: ui-monospace, monospace;
}

.model-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
  padding: 2px 6px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
  font-size: 11px;
  color: var(--muted);
}

.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px dashed var(--border);
}

:global(.dark) .status-pill.completed {
  background: #14532d;
  color: #86efac;
}

:global(.dark) .status-pill.running {
  background: #1e3a8a;
  color: #93c5fd;
}
</style>
