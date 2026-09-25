<script setup lang="ts">
import ParameterField from '@/shared/schema/ParameterField.vue'
import type { JsonObject } from '@/shared/types'
defineProps<{ value: JsonObject; schema?: JsonObject }>()
const emit = defineEmits<{ change: [value: JsonObject] }>()
</script>
<template>
  <ParameterField
    :model-value="value"
    prop="setters"
    label="处理规则 (setters)"
    :schema="schema"
    @update:model-value="emit('change', $event)"
  />
</template>
