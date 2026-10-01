<script setup lang="ts">
import AgentComposer from '@/modules/agents/ui/AgentComposer.vue'
defineOptions({ inheritAttrs: false })
const AgentComposerView = AgentComposer as any
</script>
<template><component :is="AgentComposerView" v-bind="$attrs" /></template>
