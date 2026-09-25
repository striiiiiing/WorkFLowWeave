<script setup lang="ts">
import AgentFileDrawer from '@/modules/agents/ui/AgentFileDrawer.vue'
import { useAgentsApi } from '@/modules/agents/api/dependencies'
import { useAgentFiles } from '@/modules/agents/composables/useAgentFiles'
import { onMounted } from 'vue'
defineOptions({ inheritAttrs: false })
const props = defineProps<{
  files?: ReturnType<typeof useAgentFiles>
  sessionId?: string
  initialPath?: string
}>()
const owned = props.files ?? useAgentFiles(useAgentsApi())
const AgentFileDrawerView = AgentFileDrawer as any
onMounted(() => {
  if (!props.files && props.sessionId) {
    owned.reset(props.sessionId, props.initialPath ?? 'AGENTS.md')
    void owned.read()
  }
})
</script>
<template><component :is="AgentFileDrawerView" v-bind="$attrs" :files="owned" /></template>
