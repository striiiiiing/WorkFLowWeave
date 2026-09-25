<script setup lang="ts">
import { computed } from 'vue'
import ParameterField from '@/shared/schema/ParameterField.vue'
import CredentialEditor from './CredentialEditor.vue'
import { credentialPropertyNames } from '../model/resources'
import { optionSchema } from '@/shared/schema/capabilities'
import type { SchemaCapability } from '@/shared/schema/types'
import type { JsonObject } from '@/shared/types'
import type { Credential } from '../model/types'
import type { CredentialProtector } from '../model/types'
const props = defineProps<{
  value: JsonObject
  capability?: SchemaCapability
  independent: boolean
  protect: CredentialProtector
}>()
const emit = defineEmits<{ change: [value: JsonObject] }>()
const credentialNames = computed(() => credentialPropertyNames(props.capability?.options_schema))
const editors = new Map<string, InstanceType<typeof CredentialEditor>>()
function credentialValue(name: string): Credential | null {
  const value = props.value[name]
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Credential) : null
}
function setEditor(name: string, value: unknown) {
  if (value && typeof value === 'object' && 'prepare' in value)
    editors.set(name, value as InstanceType<typeof CredentialEditor>)
  else editors.delete(name)
}
function updateCredential(name: string, value: Credential | null) {
  emit('change', { ...props.value, [name]: value })
}
async function prepare() {
  const next = { ...props.value }
  for (const name of credentialNames.value) {
    const editor = editors.get(name)
    if (editor) next[name] = await editor.prepare()
  }
  emit('change', next)
}
defineExpose({ prepare })
</script>
<template>
  <section aria-label="采集参数">
    <p v-if="capability" class="muted mb-4">{{ capability.description }}</p>
    <ParameterField
      :model-value="value"
      :excluded-properties="credentialNames"
      prop="options"
      :label="independent ? '独立采集配置 (options)' : '数据源共用配置 (options)'"
      :schema="optionSchema(capability?.options_schema, 'resource')"
      @update:model-value="emit('change', $event)"
    />
    <CredentialEditor
      v-for="name in credentialNames"
      :key="name"
      :ref="(editor) => setEditor(name, editor)"
      :model-value="credentialValue(name)"
      :label="name"
      :protect="protect"
      @update:model-value="updateCredential(name, $event)"
    />
  </section>
</template>
