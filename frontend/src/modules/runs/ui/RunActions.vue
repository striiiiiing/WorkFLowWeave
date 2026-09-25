<script setup lang="ts">
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
  <el-button :loading="pending" @click="emit('refresh')">刷新</el-button>
  <slot v-if="canContinue" name="continuation">
    <el-button @click="emit('continue')">继续讨论</el-button>
  </slot>
  <el-popconfirm v-if="active" title="确认取消执行？" @confirm="emit('cancel')">
    <template #reference>
      <el-button type="danger" :disabled="actionPending">取消执行</el-button>
    </template>
  </el-popconfirm>
  <el-button v-if="canRecover" type="primary" :loading="actionPending" @click="emit('recover')">
    恢复执行
  </el-button>
</template>
