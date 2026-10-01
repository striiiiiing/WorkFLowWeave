<script setup lang="ts">
import AgentHeader from '@/modules/agents/ui/AgentHeader.vue'
defineOptions({ inheritAttrs: false })
const AgentHeaderView = AgentHeader as any
</script>
<template><component :is="AgentHeaderView" v-bind="$attrs" /></template>
