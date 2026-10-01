<script setup lang="ts">
import AppIcon from '@/shared/ui/icons/AppIcon.vue'
defineProps<{
  pending: boolean
  active: boolean
  actionPending: boolean
  canRecover: boolean
  canContinue: boolean
}>()
const emit = defineEmits<{ refresh: []; cancel: []; recover: []; continue: [] }>()
</script>
<template>
  <el-tooltip content="重新同步运行状态">
    <el-button :loading="pending" aria-label="重新同步运行状态" @click="emit('refresh')">
      <AppIcon name="rotate" size="sm" />
    </el-button>
  </el-tooltip>
  <slot v-if="canContinue" name="continuation">
    <el-button @click="emit('continue')">继续讨论</el-button>
  </slot>
  <el-popconfirm v-if="active" title="确认取消执行？" @confirm="emit('cancel')">
    <template #reference>
      <el-button type="danger" :disabled="actionPending">取消执行</el-button>
    </template>
  </el-popconfirm>
  <el-button v-if="canRecover" type="primary" :loading="actionPending" @click="emit('recover')">
    继续中断运行
  </el-button>
</template>
