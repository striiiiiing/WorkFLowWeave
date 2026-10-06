<script setup lang="ts">
import { computed } from 'vue'
import type { SourceConfig, SourceUsageView } from '../model/public'
import { filterSources, type SourceFilter } from '../model/source/filtering'
import SourceCard from './SourceCard.vue'
const props = defineProps<{
  sources: readonly SourceConfig[]
  search: string
  filter: SourceFilter
  references: (id: string) => readonly SourceUsageView[] | undefined
  pending: boolean
  error: string
  busy: boolean
  usagePending: boolean
  usageError: string
}>()
const emit = defineEmits<{
  edit: [source: SourceConfig]
  remove: [id: string]
  enabled: [source: SourceConfig, enabled: boolean]
  workflow: [id: string]
  retryUsage: []
}>()
const filtered = computed(() =>
  filterSources(props.sources, props.search, props.filter, props.references),
)
</script>
<template>
  <el-alert
    v-if="usageError"
    :title="`工作流使用位置读取失败：${usageError}。引用数量和筛选结果暂不可用。`"
    type="error"
    :closable="false"
    show-icon
  >
    <template #default>
      <el-button size="small" @click="emit('retryUsage')">重新加载工作流使用位置</el-button>
    </template>
  </el-alert>
  <el-skeleton v-if="pending" :rows="4" />
  <div v-else class="grid grid-cols-1 gap-4">
    <SourceCard
      v-for="source in filtered"
      :key="source.id"
      :source="source"
      :usages="references(source.id)"
      :busy="busy"
      :usage-pending="usagePending"
      @edit="emit('edit', $event)"
      @remove="emit('remove', $event)"
      @enabled="(source, enabled) => emit('enabled', source, enabled)"
      @workflow="emit('workflow', $event)"
    />
  </div>
  <el-empty
    v-if="!pending && !error && !filtered.length"
    :description="
      usageError && filter !== 'all'
        ? '工作流目录不可用，无法筛选引用状态'
        : '此分类暂无匹配的数据源'
    "
  />
</template>
