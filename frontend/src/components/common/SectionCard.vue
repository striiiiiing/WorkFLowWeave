<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>
<template>
  <el-card shadow="never">
    <template #header>
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="font-semibold">{{ title }}</h2>
          <p v-if="description" class="muted text-xs mt-1">{{ description }}</p>
        </div>
        <slot name="actions" />
      </div>
    </template>
    <slot />
  </el-card>
</template>
