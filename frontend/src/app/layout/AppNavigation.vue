<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { navigation } from '@/app/navigation'
import AppIcon from '@/shared/ui/icons/AppIcon.vue'
defineProps<{ collapsed?: boolean }>()
defineEmits<{ navigate: [] }>()
const route = useRoute()
const activePath = computed(() => '/' + (route.path.split('/')[1] ?? ''))
</script>
<template>
  <nav aria-label="主导航" class="app-nav">
    <router-link
      v-for="item in navigation"
      :key="item.path"
      :to="item.path"
      :title="collapsed ? item.title : undefined"
      :class="{ active: activePath === item.path }"
      @click="$emit('navigate')"
    >
      <AppIcon :name="item.icon" />
      <span :class="{ 'sr-only': collapsed }">{{ item.title }}</span>
    </router-link>
  </nav>
</template>
