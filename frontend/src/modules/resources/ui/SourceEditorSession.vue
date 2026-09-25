<script setup lang="ts">
import type { SchemaCapability } from '@/shared/schema/types'
import type {
  SourceConfig,
  SourceConfigEditorGateway,
  SourceOverride,
  SourceSaveTarget,
  SourceUsageView,
  CredentialProtector,
} from '../model/types'
import { useSourceEditor } from '../composables/useSourceEditor'
import SourceEditorDrawer from './SourceEditorDrawer.vue'
const props = defineProps<{
  initial?: SourceConfig
  override?: SourceOverride
  target: SourceSaveTarget
  gateway: SourceConfigEditorGateway
  capabilities: readonly SchemaCapability[]
  usages?: readonly SourceUsageView[]
  protect: CredentialProtector
}>()
const emit = defineEmits<{ saved: [value: SourceConfig]; cancel: [] }>()
const editor = useSourceEditor(props, props.gateway)
</script>
<template>
  <SourceEditorDrawer
    :editor="editor"
    :initial="!!initial"
    :target="target"
    :capabilities="capabilities"
    :usages="usages"
    :protect="protect"
    @saved="emit('saved', $event)"
    @cancel="emit('cancel')"
  />
</template>
