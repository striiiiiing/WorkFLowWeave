<script setup lang="ts">
import type { HealthReport } from '../model/types'
import { healthLabels } from '../model/health'
defineProps<{ health?: HealthReport }>()
</script>
<template>
  <el-alert
    v-if="health && health.status !== 'ready'"
    :title="`系统${healthLabels[health.status]}`"
    type="warning"
    :closable="false"
  />
</template>
