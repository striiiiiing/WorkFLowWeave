<script setup lang="ts">
import { computed } from 'vue'
import type { AgentModel, AgentSession, ContextBudget } from '@/api/agents'
import AppIcon from '@/components/icons/AppIcon.vue'
import { groupAgentModels } from '@/domain/agentModels'

const props = defineProps<{
  session: AgentSession
  models: AgentModel[]
  running: boolean
  streamState: 'loading' | 'connected' | 'reconnecting' | 'closed'
}>()

const emit = defineEmits<{
  changeModel: [model: string]
  openBranches: []
  openFiles: []
  openSettings: []
  openSource: []
  openWorkflows: []
  compact: []
  fork: []
}>()

const budget = computed<ContextBudget | null>(() => props.session.context_budget)
const modelGroups = computed(() => groupAgentModels(props.models))

const tokenPercent = computed(() => {
  if (!budget.value || !budget.value.window) return 0
  return Math.min(100, Math.round((budget.value.total / budget.value.window) * 100))
})

const budgetTone = computed(() => {
  const p = tokenPercent.value
  if (p > 85) return 'danger'
  if (p > 65) return 'warning'
  return 'normal'
})

const currentModelLabel = computed(() => {
  const m = props.models.find((item) => item.reference === props.session.model)
  return m ? `${m.ai} / ${m.model}` : props.session.model || '选择供应商渠道模型'
})
</script>

<template>
  <header class="chat-header">
    <div class="header-left">
      <!-- 1. 模型选择器 Pill -->
      <el-dropdown trigger="click" @command="emit('changeModel', $event)">
        <button type="button" class="header-pill model-pill" aria-label="切换供应商渠道模型">
          <span class="pill-icon">
            <AppIcon name="sparkles" size="sm" />
          </span>
          <span class="pill-label">{{ currentModelLabel }}</span>
          <AppIcon name="chevronDown" size="sm" class="chevron" />
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <template v-for="group in modelGroups" :key="group.channel">
              <li class="px-3 py-2 text-xs text-muted" role="presentation">{{ group.channel }}</li>
              <el-dropdown-item
                v-for="item in group.models"
                :key="item.reference"
                :command="item.reference"
                :class="{ 'is-active': item.reference === session.model }"
              >
                <div class="model-option">
                  <strong>{{ item.model || item.reference }}</strong>
                  <small>{{ item.provider }} · {{ item.ai }}</small>
                </div>
              </el-dropdown-item>
            </template>
            <el-dropdown-item v-if="!models.length" disabled>暂无可用模型配置</el-dropdown-item>
            <li class="px-3 py-2">
              <a href="/resources?kind=ai" target="_blank" rel="noopener">管理供应商渠道</a>
            </li>
          </el-dropdown-menu>
        </template>
      </el-dropdown>

      <!-- 2. 分支指示器 Pill -->
      <button
        type="button"
        class="header-pill branch-pill"
        title="查看分支执行图谱"
        @click="emit('openBranches')"
      >
        <AppIcon name="fork" size="sm" />
        <span>{{ session.branch_id || 'main' }}</span>
        <span class="branch-status-dot" :class="session.status" />
      </button>

      <!-- 3. 连接状态轻量提示 -->
      <span class="connection-badge" :class="streamState">
        <span class="pulse-dot" />
        <span class="text-xs">
          {{
            streamState === 'connected'
              ? '实时已连'
              : streamState === 'reconnecting'
                ? '续传重连'
                : streamState === 'loading'
                  ? '加载中'
                  : '已同步'
          }}
        </span>
      </span>
    </div>

    <div class="header-right">
      <!-- 4. 上下文预算与智能压缩 Popover -->
      <el-popover placement="bottom-end" :width="320" trigger="hover">
        <template #reference>
          <button type="button" class="header-pill token-pill" :class="budgetTone">
            <div class="token-meter">
              <div class="token-bar" :style="{ width: `${tokenPercent}%` }" />
            </div>
            <span class="token-label">
              {{
                budget
                  ? `${Math.round(budget.total / 1000)}k / ${Math.round(budget.window / 1000)}k`
                  : '预算待计算'
              }}
            </span>
          </button>
        </template>

        <div class="budget-card">
          <div class="budget-card-header">
            <strong>上下文预算与健康度</strong>
            <span class="percentage">{{ tokenPercent }}%</span>
          </div>

          <div class="budget-progress-track">
            <div class="progress-fill" :class="budgetTone" :style="{ width: `${tokenPercent}%` }" />
          </div>

          <div v-if="budget" class="budget-breakdown">
            <p>{{ budget.estimated ? '估算用量' : '实际用量' }} · {{ budget.token_counter }}</p>
            <div class="breakdown-row">
              <span>历史消息 Tokens</span>
              <strong>{{ budget.messages.toLocaleString() }}</strong>
            </div>
            <div class="breakdown-row">
              <span>工具定义消耗</span>
              <strong>{{ budget.tools.toLocaleString() }}</strong>
            </div>
            <div class="breakdown-row">
              <span>系统提示词</span>
              <strong>{{ budget.system.toLocaleString() }}</strong>
            </div>
            <div class="breakdown-row">
              <span>输出预留空间</span>
              <strong>{{ budget.output.toLocaleString() }}</strong>
            </div>
            <div v-if="budget.trigger" class="breakdown-row trigger">
              <span>自动压缩触发阈值</span>
              <strong>{{ budget.trigger.toLocaleString() }}</strong>
            </div>
            <p v-else>历史未记录触发线，下轮重新计算。</p>
          </div>
          <div v-else class="text-xs text-muted py-2">
            尚无本轮请求消耗数据，发送第一条消息后将动态计算。
          </div>

          <div class="budget-actions">
            <el-button
              type="primary"
              size="small"
              class="w-full"
              :disabled="!session.continuable"
              @click="emit('compact')"
            >
              <AppIcon name="zap" size="sm" />
              <span>{{ running ? '排队压缩上下文' : '压缩上下文' }}</span>
            </el-button>
          </div>
        </div>
      </el-popover>

      <!-- 5. 顶部操作栏图标 -->
      <div class="header-actions">
        <el-tooltip content="以此派生新分支" placement="bottom">
          <button
            type="button"
            class="action-btn"
            aria-label="派生新分支"
            :disabled="running || !session.last_checkpoint_at"
            @click="emit('fork')"
          >
            <AppIcon name="fork" size="sm" />
          </button>
        </el-tooltip>

        <el-tooltip content="工作区文件与产物" placement="bottom">
          <button
            type="button"
            class="action-btn"
            aria-label="工作区文件"
            @click="emit('openFiles')"
          >
            <AppIcon name="file" size="sm" />
          </button>
        </el-tooltip>

        <el-tooltip content="只读 Workflow 来源" placement="bottom">
          <button
            type="button"
            class="action-btn"
            aria-label="Workflow 来源"
            @click="emit('openSource')"
          >
            <AppIcon name="info" size="sm" />
          </button>
        </el-tooltip>

        <el-tooltip content="Workflow 历史" placement="bottom">
          <button
            type="button"
            class="action-btn"
            aria-label="Workflow 历史"
            @click="emit('openWorkflows')"
          >
            <AppIcon name="history" size="sm" />
          </button>
        </el-tooltip>

        <el-tooltip content="全局设置与沙箱" placement="bottom">
          <button
            type="button"
            class="action-btn"
            aria-label="全局设置"
            @click="emit('openSettings')"
          >
            <AppIcon name="settings" size="sm" />
          </button>
        </el-tooltip>
      </div>
    </div>
  </header>
</template>

<style scoped>
.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  min-height: 52px;
  gap: 12px;
}

.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.header-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--el-text-color-primary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.header-pill:hover {
  background: var(--el-fill-color-light);
  border-color: color-mix(in srgb, var(--el-color-primary) 30%, transparent);
}

.model-pill {
  font-weight: 600;
}

.model-pill .pill-icon {
  color: var(--el-color-primary);
  display: grid;
  place-items: center;
}

.model-pill .chevron {
  color: var(--muted);
  transition: transform 0.15s ease;
}

.branch-pill {
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 12px;
  color: var(--muted);
}

.branch-pill:hover {
  color: var(--el-text-color-primary);
}

.branch-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #94a3b8;
}

.branch-status-dot.running {
  background: #10b981;
  box-shadow: 0 0 6px #10b981;
}

.branch-status-dot.completed {
  background: #3b82f6;
}

.connection-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--muted);
  padding: 2px 6px;
  border-radius: 6px;
}

.pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #94a3b8;
}

.connection-badge.connected .pulse-dot {
  background: #10b981;
}

.connection-badge.reconnecting .pulse-dot {
  background: #f59e0b;
  animation: blink 1s infinite;
}

@keyframes blink {
  50% {
    opacity: 0.2;
  }
}

.token-pill {
  padding: 4px 8px;
  font-family: ui-monospace, monospace;
  font-size: 11px;
  gap: 8px;
}

.token-meter {
  width: 38px;
  height: 5px;
  background: var(--el-fill-color);
  border-radius: 3px;
  overflow: hidden;
}

.token-bar {
  height: 100%;
  background: var(--el-color-primary);
  transition: width 0.3s ease;
}

.token-pill.warning .token-bar {
  background: #f59e0b;
}

.token-pill.danger .token-bar {
  background: #ef4444;
}

.budget-card {
  padding: 4px;
}

.budget-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.budget-card-header strong {
  font-size: 13px;
  color: var(--el-text-color-primary);
}

.budget-card-header .percentage {
  font-size: 13px;
  font-weight: 700;
  font-family: ui-monospace, monospace;
  color: var(--el-color-primary);
}

.budget-progress-track {
  height: 6px;
  background: var(--el-fill-color);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 12px;
}

.progress-fill {
  height: 100%;
  background: var(--el-color-primary);
  transition: width 0.3s ease;
}

.progress-fill.warning {
  background: #f59e0b;
}

.progress-fill.danger {
  background: #ef4444;
}

.budget-breakdown {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  margin-bottom: 12px;
}

.breakdown-row {
  display: flex;
  justify-content: space-between;
  color: var(--muted);
}

.breakdown-row strong {
  font-family: ui-monospace, monospace;
  color: var(--el-text-color-primary);
}

.breakdown-row.trigger {
  color: #f59e0b;
  border-top: 1px dashed var(--border);
  padding-top: 4px;
  margin-top: 2px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.action-btn {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  transition: all 0.15s ease;
}

.action-btn:hover:not(:disabled) {
  background: var(--el-fill-color-light);
  color: var(--el-text-color-primary);
}

.action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.model-option {
  display: flex;
  flex-direction: column;
  padding: 2px 0;
}

.model-option small {
  font-size: 11px;
  color: var(--muted);
}

@media (max-width: 640px) {
  .chat-header {
    flex-wrap: wrap;
    padding: 8px;
  }
  .header-left,
  .header-right {
    flex-wrap: wrap;
    max-width: 100%;
  }
  .model-pill {
    max-width: 240px;
  }
  .pill-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .connection-badge,
  .token-pill {
    display: none;
  }
}
</style>
