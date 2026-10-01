<script setup lang="ts">
import type { useAgentBranches } from '../composables/useAgentBranches'

defineProps<{ controller: ReturnType<typeof useAgentBranches> }>()
const emit = defineEmits<{ confirm: [] }>()
</script>

<template>
  <el-dialog
    :model-value="!!controller.event.value"
    title="编辑指令并派生新分支"
    width="min(90vw, 620px)"
    :close-on-click-modal="!controller.action.pending.value"
    :close-on-press-escape="!controller.action.pending.value"
    :show-close="!controller.action.pending.value"
    @close="controller.close"
  >
    <p class="text-sm text-muted mb-2">从此消息节点创建独立分支并发送更新后的指令。</p>
    <el-alert
      v-if="controller.action.error.value"
      :title="controller.action.error.value"
      type="error"
      :closable="false"
    />
    <p v-if="controller.branch.value">
      分支 {{ controller.branch.value.branch_id }} 已创建；重试沿用同一请求编号。
    </p>
    <el-input
      v-model="controller.draft.value"
      :disabled="!!controller.branch.value || controller.action.pending.value"
      type="textarea"
      :rows="6"
      aria-label="分支消息"
    />
    <template #footer>
      <el-button :disabled="controller.action.pending.value" @click="controller.close">
        取消
      </el-button>
      <el-button type="primary" :loading="controller.action.pending.value" @click="emit('confirm')">
        确认创建分支并发送
      </el-button>
    </template>
  </el-dialog>
</template>
