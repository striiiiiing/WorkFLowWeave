<script setup lang="ts">
import { computed } from 'vue'
import { resourcesApi } from '@/api/resources'
import {
  SourceEditorSession,
  type SourceConfig,
  type SourceOverride,
  type SourceConfigEditorGateway,
  type SourceSaveTarget,
} from '@/modules/resources/public'
const props = defineProps<{
  initial?: SourceConfig
  override?: SourceOverride
  local?: boolean
  linkedCount?: number
}>()
const emit = defineEmits<{ saved: [value: SourceConfig]; cancel: [] }>()
const target = computed<SourceSaveTarget>(() =>
  props.local
    ? { kind: 'workflow-draft', workflowId: '', sourceId: props.initial!.id }
    : { kind: 'shared-resource', resourceId: props.initial?.id ?? '' },
)
const gateway = computed<SourceConfigEditorGateway>(() => {
  const existing = !!props.initial
  return {
    resolve: resourcesApi.resolveSource,
    async save(target, value) {
      if (target.kind === 'workflow-draft') return
      if (existing) await resourcesApi.replace('sources', target.resourceId, value)
      else await resourcesApi.create('sources', value)
    },
  }
})
</script>
<template>
  <SourceEditorSession
    :key="`${target.kind}:${initial?.id ?? 'new'}`"
    :initial="initial"
    :override="override"
    :target="target"
    :gateway="gateway"
    @saved="emit('saved', $event)"
    @cancel="emit('cancel')"
  />
</template>
