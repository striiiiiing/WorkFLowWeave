<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import AppIcon from '@/shared/ui/icons/AppIcon.vue'
import AgentSlashMenu, { type SlashCommand } from './AgentSlashMenu.vue'

const props = defineProps<{
  draft: string
  running: boolean
  disabled?: boolean
  sendUncertain?: boolean
  sendRetrySafe?: boolean
  commands: SlashCommand[]
  pending?: boolean
  stopPending?: boolean
}>()

const emit = defineEmits<{
  'update:draft': [text: string]
  send: []
  stop: []
  executeCommand: [cmd: SlashCommand]
}>()

const textareaRef = ref<HTMLTextAreaElement>()
const slashMenuRef = ref<InstanceType<typeof AgentSlashMenu>>()
const showSlashMenu = ref(false)
const slashQuery = ref('')
const menuVisible = computed(
  () =>
    showSlashMenu.value &&
    props.commands.some(
      (cmd) => !cmd.disabled && cmd.key.toLowerCase().startsWith(slashQuery.value.toLowerCase()),
    ),
)
const canSend = computed(
  () =>
    Boolean(props.draft.trim()) &&
    !props.disabled &&
    !props.pending &&
    !(props.sendUncertain && props.sendRetrySafe === false),
)

// Watch input changes for slash command trigger
watch(
  () => props.draft,
  (val) => {
    // If text starts with '/' or contains a slash command trigger
    if (/^\/\S*$/.test(val)) {
      showSlashMenu.value = true
      slashQuery.value = val
    } else {
      showSlashMenu.value = false
      slashQuery.value = ''
    }
  },
)

function onKeyDown(e: KeyboardEvent) {
  if (e.isComposing) return
  if (menuVisible.value) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      slashMenuRef.value?.moveSelection('down')
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      slashMenuRef.value?.moveSelection('up')
      return
    }
    if ((e.key === 'Enter' && !e.shiftKey) || e.key === 'Tab') {
      e.preventDefault()
      slashMenuRef.value?.selectActive()
      return
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      showSlashMenu.value = false
      return
    }
  }

  // Normal enter to send
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    submit()
  }
  if (e.key === 'Escape' && props.running && !props.stopPending) emit('stop')
}

function submit() {
  if (!canSend.value) return
  const command = props.commands.find((item) => item.key === props.draft.trim())
  if (command) {
    if (!command.disabled) selectCommand(command)
    return
  }
  emit('send')
}

function selectCommand(cmd: SlashCommand) {
  if (props.pending || props.disabled || cmd.disabled) return
  showSlashMenu.value = false
  emit('update:draft', '')
  emit('executeCommand', cmd)
}

function triggerSlashManually() {
  if (!props.draft.startsWith('/')) {
    emit('update:draft', '/' + props.draft)
  }
  showSlashMenu.value = true
  nextTick(() => {
    textareaRef.value?.focus()
  })
}

function handleInput(e: Event) {
  const target = e.target as HTMLTextAreaElement
  emit('update:draft', target.value)

  // Auto resize
  target.style.height = 'auto'
  target.style.height = Math.min(target.scrollHeight, 160) + 'px'
}
</script>

<template>
  <form class="composer-container" aria-label="Agent 输入" @submit.prevent="submit">
    <!-- 1. 浮动运行状态胶囊 (暂停 / 停止按钮集成在此) -->
    <transition name="fade">
      <div v-if="running" class="running-capsule">
        <div class="capsule-pulse">
          <span class="pulse-ring" />
          <span class="pulse-core" />
        </div>
        <span class="capsule-text">Agent 正在执行与分析中...</span>
        <button
          type="button"
          class="capsule-stop-btn"
          :disabled="stopPending"
          @click="emit('stop')"
        >
          <AppIcon name="square" size="sm" />
          <span>{{ stopPending ? '正在停止...' : '暂停 / 停止' }}</span>
        </button>
      </div>
    </transition>

    <!-- 2. 发送异常提示 -->
    <div v-if="sendUncertain" class="composer-alert">
      <span v-if="sendRetrySafe !== false">
        发送结果未知，草稿与请求编号已保留。可点击发送重试。
      </span>
      <span v-else>操作结果未知；请先检查会话列表与执行历史，确认未生效后再编辑指令重试。</span>
    </div>

    <!-- 3. 输入框主卡片 -->
    <div class="composer-box" :class="{ focused: true, 'is-running': running }">
      <!-- 斜杠指令浮层 -->
      <AgentSlashMenu
        ref="slashMenuRef"
        :visible="menuVisible"
        :query="slashQuery"
        :commands="commands"
        @select="selectCommand"
        @close="showSlashMenu = false"
      />

      <textarea
        ref="textareaRef"
        :value="draft"
        class="composer-textarea"
        aria-label="Agent 消息"
        :placeholder="
          disabled
            ? '当前会话不可继续'
            : running
              ? '输入补充说明，发送后排队；/ 可打开命令菜单'
              : '向 Agent 发送指令或问题，输入 / 可唤起快捷功能...'
        "
        :disabled="disabled"
        rows="2"
        @input="handleInput"
        @keydown="onKeyDown"
      />

      <!-- 底部控制条 -->
      <div class="composer-bottom">
        <div class="composer-tools">
          <button
            type="button"
            class="tool-btn slash-btn"
            title="输入快捷指令 (/)"
            :disabled="disabled"
            @click="triggerSlashManually"
          >
            <span class="slash-char">/</span>
            <span class="tool-label">快捷指令</span>
          </button>
          <span class="keyboard-tip">Shift + Enter 换行</span>
        </div>

        <div class="composer-actions">
          <!-- 运行中：停止按钮 -->
          <button
            v-if="running"
            type="button"
            class="action-circle-btn stop-btn"
            title="停止生成 (Stop)"
            :disabled="stopPending"
            @click="emit('stop')"
          >
            <AppIcon name="square" size="sm" />
          </button>

          <!-- 空闲中：发送按钮 -->
          <button
            type="submit"
            class="action-circle-btn send-btn"
            :disabled="!canSend"
            :title="running ? '追加到队列 (Enter)' : '发送 (Enter)'"
            :aria-label="running ? '追加到队列' : '发送'"
          >
            <AppIcon name="send" size="sm" />
          </button>
        </div>
      </div>
    </div>
  </form>
</template>

<style scoped>
.composer-container {
  position: relative;
  flex: 0 0 auto;
  width: 100%;
  max-width: 820px;
  margin: 0 auto;
  padding: 12px 16px 16px;
}

.running-capsule {
  position: absolute;
  top: -26px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 5px 14px;
  background: var(--surface);
  border: 1px solid color-mix(in srgb, var(--el-color-primary) 30%, transparent);
  border-radius: 20px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  font-size: 12px;
  z-index: 10;
  backdrop-filter: blur(8px);
}

.capsule-pulse {
  position: relative;
  width: 10px;
  height: 10px;
  display: grid;
  place-items: center;
}

.pulse-core {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
}

.pulse-ring {
  position: absolute;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid #10b981;
  animation: pulseRipple 1.6s infinite;
}

@keyframes pulseRipple {
  0% {
    transform: scale(0.6);
    opacity: 1;
  }
  100% {
    transform: scale(1.6);
    opacity: 0;
  }
}

.capsule-text {
  white-space: nowrap;
  font-weight: 500;
  color: var(--el-text-color-primary);
}

.capsule-stop-btn {
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 12px;
  border: 1px solid #fca5a5;
  background: #fee2e2;
  color: #b91c1c;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.capsule-stop-btn:hover {
  background: #fecaca;
}

.composer-alert {
  padding: 8px 12px;
  margin-bottom: 8px;
  border-radius: 8px;
  background: #fef3c7;
  border: 1px solid #fde68a;
  color: #92400e;
  font-size: 12px;
}

.composer-box {
  position: relative;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow:
    0 4px 20px -2px rgba(15, 23, 42, 0.06),
    0 2px 6px rgba(15, 23, 42, 0.04);
  padding: 12px 14px 10px;
  transition: all 0.2s ease;
}

.composer-box:focus-within {
  border-color: color-mix(in srgb, var(--el-color-primary) 50%, transparent);
  box-shadow:
    0 4px 24px -2px rgba(37, 99, 235, 0.12),
    0 2px 8px rgba(15, 23, 42, 0.05);
}

.composer-textarea {
  width: 100%;
  border: none;
  background: transparent;
  color: var(--el-text-color-primary);
  font-family: inherit;
  font-size: 14px;
  line-height: 1.6;
  resize: none;
  outline: none;
  max-height: 160px;
  min-height: 48px;
  box-sizing: border-box;
}

.composer-textarea::placeholder {
  color: var(--muted);
}

.composer-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid color-mix(in srgb, var(--border) 60%, transparent);
}

.composer-tools {
  display: flex;
  align-items: center;
  gap: 10px;
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--el-fill-color-light);
  color: var(--muted);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tool-btn:hover:not(:disabled) {
  color: var(--el-color-primary);
  border-color: var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary) 8%, var(--surface));
}

.slash-char {
  font-family: ui-monospace, monospace;
  font-weight: 700;
  color: var(--el-color-primary);
}

.keyboard-tip {
  font-size: 11px;
  color: var(--muted);
}

.action-circle-btn {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: none;
  cursor: pointer;
  transition: all 0.15s ease;
}

.send-btn {
  background: var(--el-color-primary);
  color: #fff;
}

.send-btn:hover:not(:disabled) {
  opacity: 0.9;
  transform: scale(1.05);
}

.send-btn:disabled {
  background: var(--el-fill-color);
  color: var(--muted);
  cursor: not-allowed;
  transform: none;
}

.stop-btn {
  background: #ef4444;
  color: #fff;
  animation: stopPulse 1.2s infinite;
}

@keyframes stopPulse {
  50% {
    transform: scale(0.95);
  }
}

.fade-enter-active,
.fade-leave-active {
  transition:
    opacity 0.2s ease,
    transform 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translate(-50%, 6px);
}

:global(.dark) .composer-box {
  background: #1e293b;
  border-color: #334155;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
}

:global(.dark) .capsule-stop-btn {
  background: #450a0a;
  border-color: #7f1d1d;
  color: #fca5a5;
}

:global(.dark) .running-capsule {
  background: #1e293b;
  border-color: #334155;
}
</style>
