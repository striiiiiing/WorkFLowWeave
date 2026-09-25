<script setup lang="ts">
import { computed } from 'vue'
import type { useSystemHealth } from '../composables/useSystemHealth'
import SectionCard from '@/shared/ui/SectionCard.vue'
const props = defineProps<{ query: ReturnType<typeof useSystemHealth> }>()
const health = computed(() => props.query.data.value)
const healthError = computed(() => props.query.error.value)
</script>
<template>
  <SectionCard title="组件健康状态" class="mt-6">
    <el-table v-if="health" :data="health.components">
      <el-table-column prop="component" label="组件" />
      <el-table-column prop="status" label="状态" />
      <el-table-column label="错误信息" min-width="220">
        <template #default="{ row }">{{ row.error?.message ?? '—' }}</template>
      </el-table-column>
    </el-table>
    <p v-else class="muted py-4">{{ healthError || '正在读取组件诊断' }}</p>
  </SectionCard>
</template>
