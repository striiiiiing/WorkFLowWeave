<script setup lang="ts">
import AgentBranchDrawer from '@/modules/agents/ui/AgentBranchDrawer.vue'
defineOptions({ inheritAttrs: false })
const AgentBranchDrawerView = AgentBranchDrawer as any
</script>
<template><component :is="AgentBranchDrawerView" v-bind="$attrs" /></template>
