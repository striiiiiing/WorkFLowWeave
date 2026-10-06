<script setup lang="ts">
import type {
  SourceConfig,
  SourceConfigEditorGateway,
  SourceOverride,
  SourceSaveTarget,
  SourceUsageView,
} from '../model/public'
import { useSourceEditor } from '../composables/useSourceEditor'
import SourceEditorDrawer from './SourceEditorDrawer.vue'
const props = defineProps<{
  initial?: SourceConfig
  override?: SourceOverride
  target: SourceSaveTarget
  gateway: SourceConfigEditorGateway
  usages?: readonly SourceUsageView[]
}>()
const emit = defineEmits<{ saved: [value: SourceConfig]; cancel: [] }>()
const editor = useSourceEditor(props, props.gateway)
</script>
<template>
  <SourceEditorDrawer
    :editor="editor"
    :initial="!!initial"
    :target="target"
    :usages="usages"
    @saved="emit('saved', $event)"
    @cancel="emit('cancel')"
  />
</template>
