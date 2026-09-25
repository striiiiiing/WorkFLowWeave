<script setup lang="ts">
import type { usePluginReload } from '../composables/usePluginReload'
defineProps<{ action: ReturnType<typeof usePluginReload> }>()
</script>
<template>
  <el-button :loading="action.pending.value" @click="action.reload">重新加载插件</el-button>
</template>
