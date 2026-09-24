<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>
<template>
  <header class="page-heading">
    <div>
      <h1>{{ title }}</h1>
      <p v-if="description" class="muted mt-1">{{ description }}</p>
    </div>
    <div class="flex flex-wrap items-center gap-2"><slot /></div>
  </header>
</template>
