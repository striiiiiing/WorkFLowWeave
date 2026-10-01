<script setup lang="ts">
import ContinueInAgent from '@/pages/integrations/ContinueInAgent.vue'

defineProps<{ workflowId?: string; workflowSessionId?: string }>()
</script>

<template>
  <ContinueInAgent :workflow-id="workflowId" :workflow-session-id="workflowSessionId" />
</template>
