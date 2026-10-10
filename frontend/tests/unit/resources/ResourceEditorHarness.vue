<script setup lang="ts">
// Test-only assembly of the actual editors; production pages own this catalog and gateway.
import { computed, provide } from 'vue'
import { resourcesApi } from '@/app/services'
import { systemApi } from '@/app/services'
import {
  resourcesApiKey,
  type SourceConfig,
  type SourceConfigEditorGateway,
  type EditableKind,
  type EditableResource,
} from '@/modules/resources/public'
import { useQuery } from '@/shared/async/useQuery'
import { useSourceEditor } from '@/modules/resources/composables/useSourceEditor'
import SourceConfigEditor from '@/modules/resources/ui/SourceConfigEditor.vue'
import ChannelEditor from '@/modules/resources/ui/ChannelEditor.vue'
import AIProviderEditor from '@/modules/resources/ui/AIProviderEditor.vue'
const props = defineProps<{ kind: EditableKind; initial?: EditableResource }>()
const emit = defineEmits<{ saved: [value?: EditableResource]; cancel: [] }>()
provide(resourcesApiKey, resourcesApi)
const catalog = useQuery((signal) => systemApi.plugins(signal))
const capabilities = computed(
  () =>
    catalog.data.value?.filter(
      (item) => props.kind === 'channels' && item.kind === 'channel',
    ) ?? [],
)
const target = { kind: 'shared-resource' as const, resourceId: props.initial?.id ?? '' }
const gateway: SourceConfigEditorGateway = {
  resolve: async () => props.initial as SourceConfig,
  async save(target, value) {
    if (target.kind !== 'shared-resource') throw new Error('Unexpected target')
    if (props.initial) await resourcesApi.replace('sources', target.resourceId, value)
    else await resourcesApi.create('sources', value)
  },
}
const editor =
  props.kind === 'sources'
    ? useSourceEditor({ initial: props.initial as SourceConfig | undefined, target }, gateway)
    : undefined
</script>
<template>
  <SourceConfigEditor
    v-if="editor"
    :editor="editor"
    :initial="!!initial"
    :target="target"
    @saved="emit('saved', $event)"
    @cancel="emit('cancel')"
  />
  <AIProviderEditor
    v-else-if="kind === 'ai'"
    :initial="initial && 'provider' in initial ? initial : undefined"
    @saved="emit('saved', $event)"
    @cancel="emit('cancel')"
  />
  <ChannelEditor
    v-else
    :initial="initial && 'channel' in initial ? initial : undefined"
    :capabilities="capabilities"
    @saved="emit('saved', $event)"
    @cancel="emit('cancel')"
  />
</template>
