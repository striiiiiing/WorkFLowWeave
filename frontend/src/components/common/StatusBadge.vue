<script setup lang="ts">
import { sessionStates } from '@/domain/session'
import type { SessionStatus } from '@/types'
defineProps<{ status: SessionStatus }>()
</script>
<template>
  <el-tag :type="sessionStates[status].type" effect="light">
    {{ sessionStates[status].label }}
  </el-tag>
</template>
