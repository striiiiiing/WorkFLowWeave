<script setup lang="ts">
import AgentModelSelect from '@/modules/agents/ui/AgentModelSelect.vue'
defineOptions({ inheritAttrs: false })
const AgentModelSelectView = AgentModelSelect as any
defineProps<{
  modelValue: string
  models: import('@/modules/agents/public').AgentModel[]
  label: string
  optional?: boolean
  disabled?: boolean
}>()
</script>
<template><component :is="AgentModelSelectView" v-bind="{ ...$props, ...$attrs }" /></template>
