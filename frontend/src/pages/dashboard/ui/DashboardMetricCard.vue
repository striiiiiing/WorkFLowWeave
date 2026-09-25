<script setup lang="ts">
import { formatUpdated, staleMessage } from '@/shared/async/presentation'
defineProps<{
  label: string
  value: string | number
  description: string
  pending: boolean
  error: string
  hasData: boolean
  readAt?: number
}>()
</script>
<template>
  <el-card shadow="hover">
    <p class="muted">{{ label }}</p>
    <p class="text-3xl font-bold text-blue-600 dark:text-blue-400 my-3">{{ value }}</p>
    <p class="muted text-xs">{{ description }}</p>
    <p v-if="pending" class="muted text-xs mt-2">正在读取</p>
    <p v-else-if="error" class="text-red-600 text-xs mt-2" role="alert">
      {{ staleMessage(error, hasData, readAt) }}
    </p>
    <p v-else class="muted text-xs mt-2">{{ formatUpdated(readAt) }}</p>
  </el-card>
</template>
