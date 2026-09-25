<script setup lang="ts">
import AgentToolCall from '@/modules/agents/ui/AgentToolCall.vue'
defineOptions({ inheritAttrs: false })
const AgentToolCallView = AgentToolCall as any
</script>
<template><component :is="AgentToolCallView" v-bind="$attrs" /></template>
