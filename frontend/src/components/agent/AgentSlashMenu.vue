<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppIcon from '@/components/icons/AppIcon.vue'
import type { IconName } from '@/components/icons/registry'

export interface SlashCommand {
  key: string
  label: string
  description: string
  icon: IconName
  badge?: string
  shortcut?: string
  disabled?: boolean
  action: () => void
}

const props = defineProps<{
  visible: boolean
  query: string
  commands: SlashCommand[]
}>()

const emit = defineEmits<{
  select: [command: SlashCommand]
  close: []
}>()

const activeIndex = ref(0)

const filtered = computed(() =>
  props.commands.filter(
    (cmd) => !cmd.disabled && cmd.key.toLowerCase().startsWith(props.query.toLowerCase()),
  ),
)

watch(
  () => props.query,
  () => {
    activeIndex.value = 0
  },
)

function moveSelection(direction: 'up' | 'down') {
  if (!filtered.value.length) return
  if (direction === 'down') {
    activeIndex.value = (activeIndex.value + 1) % filtered.value.length
  } else {
    activeIndex.value = (activeIndex.value - 1 + filtered.value.length) % filtered.value.length
  }
}

function selectActive() {
  const item = filtered.value[activeIndex.value]
  if (item) {
    emit('select', item)
  }
}

defineExpose({
  moveSelection,
  selectActive,
})
</script>

<template>
  <div v-if="visible && filtered.length > 0" class="slash-palette">
    <div class="palette-header">
      <span class="palette-title">
        <AppIcon name="sparkles" size="sm" />
        <span>快捷指令</span>
      </span>
      <span class="palette-hint">↑↓ 切换 · Enter 确认 · Esc 关闭</span>
    </div>

    <div class="palette-list" role="listbox">
      <button
        v-for="(cmd, index) in filtered"
        :key="cmd.key"
        type="button"
        role="option"
        :aria-selected="index === activeIndex"
        class="palette-item"
        :class="{ active: index === activeIndex }"
        @click="emit('select', cmd)"
        @mouseenter="activeIndex = index"
      >
        <span class="cmd-icon">
          <AppIcon :name="cmd.icon" size="sm" />
        </span>
        <div class="cmd-info">
          <div class="cmd-top">
            <span class="cmd-key">{{ cmd.key }}</span>
            <span class="cmd-label">{{ cmd.label }}</span>
            <span v-if="cmd.badge" class="cmd-badge">{{ cmd.badge }}</span>
          </div>
          <p class="cmd-desc">{{ cmd.description }}</p>
        </div>
        <span v-if="cmd.shortcut" class="cmd-shortcut">{{ cmd.shortcut }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.slash-palette {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  width: 100%;
  max-width: 440px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow:
    0 12px 32px -4px rgba(15, 23, 42, 0.16),
    0 4px 12px rgba(15, 23, 42, 0.08);
  overflow: hidden;
  z-index: 50;
  backdrop-filter: blur(12px);
  animation: slideUp 0.15s ease-out;
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.palette-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: var(--el-fill-color-light);
  border-bottom: 1px solid var(--border);
  font-size: 11px;
  color: var(--muted);
}

.palette-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: var(--el-color-primary);
}

.palette-list {
  max-height: 280px;
  overflow-y: auto;
  padding: 6px;
}

.palette-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: all 0.12s ease;
}

.palette-item:hover,
.palette-item.active {
  background: var(--el-fill-color-light);
}

.palette-item.active {
  background: color-mix(in srgb, var(--el-color-primary) 8%, var(--surface));
}

.cmd-icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: var(--el-fill-color);
  color: var(--el-color-primary);
  flex-shrink: 0;
}

.cmd-info {
  flex: 1;
  min-width: 0;
}

.cmd-top {
  display: flex;
  align-items: center;
  gap: 6px;
}

.cmd-key {
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-weight: 700;
  font-size: 13px;
  color: var(--el-color-primary);
}

.cmd-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--el-text-color-primary);
}

.cmd-badge {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 4px;
  background: color-mix(in srgb, var(--el-color-primary) 12%, transparent);
  color: var(--el-color-primary);
  font-weight: 600;
}

.cmd-desc {
  margin: 2px 0 0;
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cmd-shortcut {
  font-size: 11px;
  color: var(--muted);
  font-family: ui-monospace, monospace;
  background: var(--el-fill-color);
  padding: 2px 6px;
  border-radius: 4px;
}

:global(.dark) .slash-palette {
  background: #1e293b;
  border-color: #334155;
  box-shadow: 0 16px 36px -4px rgba(0, 0, 0, 0.4);
}

:global(.dark) .palette-header {
  background: #0f172a;
  border-color: #334155;
}

:global(.dark) .cmd-icon {
  background: #0f172a;
}
</style>
