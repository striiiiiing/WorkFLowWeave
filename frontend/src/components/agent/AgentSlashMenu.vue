<script setup lang="ts">
import AgentSlashMenu from '@/modules/agents/ui/AgentSlashMenu.vue'
defineOptions({ inheritAttrs: false })
export type { SlashCommand } from '@/modules/agents/ui/AgentSlashMenu.vue'
const AgentSlashMenuView = AgentSlashMenu as any
</script>
<template><component :is="AgentSlashMenuView" v-bind="$attrs" /></template>
