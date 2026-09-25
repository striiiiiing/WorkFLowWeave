<script setup lang="ts">
// P7 replaces this temporary route composition when Agent continuation is migrated.
import RunDetailPage from '@/pages/runs/RunDetailPage.vue'
import AgentContinueButton from '@/components/agent/AgentContinueButton.vue'
</script>
<template>
  <RunDetailPage>
    <template #continuation="{ context }">
      <AgentContinueButton v-if="context" :workflow-session-id="context.session.session_id" />
    </template>
  </RunDetailPage>
</template>
