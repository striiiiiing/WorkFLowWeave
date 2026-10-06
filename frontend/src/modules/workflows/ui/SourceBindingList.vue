<script setup lang="ts">
import type { SourceConfig, SourceUsageView } from '@/modules/resources/public'
import type { WorkflowDefinition } from '../model/public'
import SourceBindingItem from './SourceBindingItem.vue'

const props = defineProps<{
  draft: WorkflowDefinition
  sources: readonly SourceConfig[]
  usage?: (id: string) => readonly SourceUsageView[] | undefined
  pending: boolean
  refreshing?: boolean
  restoreErrors: Readonly<Record<string, string>>
}>()
const emit = defineEmits<{
  move: [index: number, delta: number]
  edit: [sourceId: string]
  detach: [sourceId: string]
  restore: [sourceId: string]
  publish: [sourceId: string]
  refresh: []
  remove: [sourceId: string]
}>()

function sourceById(id: string) {
  return (
    props.draft.source_overrides[id]?.source ?? props.sources.find((source) => source.id === id)
  )
}
function sharedCount(id: string) {
  return (props.usage?.(id) ?? []).filter((item) => !item.detached).length
}
function hasShared(id: string) {
  return props.sources.some((source) => source.id === id)
}
</script>

<template>
  <SourceBindingItem
    v-for="(sourceId, index) in draft.sources"
    :key="sourceId"
    :source-id="sourceId"
    :index="index"
    :total="draft.sources.length"
    :source="sourceById(sourceId)"
    :override="draft.source_overrides[sourceId]"
    :shared-count="sharedCount(sourceId)"
    :has-shared="hasShared(sourceId)"
    :pending="pending"
    :refreshing="refreshing"
    :restore-error="restoreErrors[sourceId]"
    @move="emit('move', index, $event)"
    @edit="emit('edit', sourceId)"
    @detach="emit('detach', sourceId)"
    @restore="emit('restore', sourceId)"
    @publish="emit('publish', sourceId)"
    @refresh="emit('refresh')"
    @remove="emit('remove', sourceId)"
  />
</template>
