<script setup lang="ts">
import AgentGlobalSettingsModal from '@/modules/agents/ui/AgentGlobalSettingsModal.vue'
import { useAgentsApi } from '@/modules/agents/api/dependencies'
import { useAgentSettings } from '@/modules/agents/composables/useAgentSettings'
defineOptions({ inheritAttrs: false })
const props = defineProps<{ controller?: ReturnType<typeof useAgentSettings> }>()
const owned = props.controller ?? useAgentSettings(useAgentsApi())
const AgentGlobalSettingsModalView = AgentGlobalSettingsModal as any
</script>
<template>
  <component :is="AgentGlobalSettingsModalView" v-bind="$attrs" :controller="owned" />
</template>
