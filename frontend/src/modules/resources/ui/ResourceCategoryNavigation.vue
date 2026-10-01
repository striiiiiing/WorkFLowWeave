<script setup lang="ts">
import { resourceKinds, type EditableKind } from '../model/resources'
defineProps<{ value: EditableKind }>()
const emit = defineEmits<{ change: [value: EditableKind] }>()
</script>
<template>
  <el-tabs :model-value="value" @update:model-value="emit('change', $event as EditableKind)">
    <el-tab-pane
      v-for="category in resourceKinds"
      :key="category.key"
      :name="category.key"
      :label="category.label"
    />
  </el-tabs>
</template>
