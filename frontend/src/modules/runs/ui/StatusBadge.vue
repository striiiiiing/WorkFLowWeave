<script setup lang="ts">
import { sessionStates } from '@/modules/workflows/model/public'
import type { SessionStatus } from '@/modules/workflows/model/public'
defineProps<{ status: SessionStatus }>()
</script>
<template>
  <el-tag :type="sessionStates[status].type" effect="light">
    {{ sessionStates[status].label }}
  </el-tag>
</template>
