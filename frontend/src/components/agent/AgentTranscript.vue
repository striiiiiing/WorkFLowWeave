<script setup lang="ts">
import AgentTranscript from '@/modules/agents/ui/AgentTranscript.vue'
defineOptions({ inheritAttrs: false })
const AgentTranscriptView = AgentTranscript as any
</script>
<template><component :is="AgentTranscriptView" v-bind="$attrs" /></template>
