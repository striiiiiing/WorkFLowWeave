<script setup lang="ts">
import { SessionTable, type useRecentRuns } from '@/modules/runs/public'
import { staleMessage } from '@/shared/async/presentation'
import SectionCard from '@/shared/ui/SectionCard.vue'
defineProps<{ query: ReturnType<typeof useRecentRuns> }>()
const emit = defineEmits<{ open: [id: string]; all: [] }>()
</script>
<template>
  <SectionCard title="最近执行历史">
    <template #actions>
      <button type="button" class="min-h-11" @click="emit('all')">查看全部历史 →</button>
    </template>
    <el-alert
      v-if="query.error.value"
      :title="staleMessage(query.error.value, !!query.data.value, query.readAt.value)"
      type="error"
      :closable="false"
      show-icon
      class="mb-4"
    />
    <SessionTable
      :sessions="query.data.value ?? []"
      :loading="query.pending.value"
      @open="(id) => emit('open', id)"
    />
  </SectionCard>
</template>
