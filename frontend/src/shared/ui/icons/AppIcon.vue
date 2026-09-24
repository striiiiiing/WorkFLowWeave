<script setup lang="ts">
import { icons, type IconName } from './registry'
withDefaults(defineProps<{ name: IconName; size?: 'sm' | 'md' | 'lg' }>(), { size: 'md' })
const sizes = { sm: 16, md: 20, lg: 24 }
</script>
<template>
  <component
    :is="icons[name]"
    :size="sizes[size]"
    :stroke-width="1.75"
    aria-hidden="true"
    class="shrink-0"
  />
</template>
