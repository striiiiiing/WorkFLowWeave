<script setup lang="ts">
import type { SourceFilter } from '../model/sourceFiltering'
defineProps<{ search: string; filter: SourceFilter }>()
const emit = defineEmits<{ search: [value: string]; filter: [value: SourceFilter] }>()
</script>
<template>
  <div class="flex flex-wrap items-center gap-3 mb-4">
    <el-input
      :model-value="search"
      clearable
      placeholder="搜索名称、编号、说明或采集器"
      aria-label="搜索数据源"
      class="max-w-md"
      @update:model-value="emit('search', $event)"
    />
    <el-radio-group
      :model-value="filter"
      aria-label="按工作流使用情况筛选"
      class="flex max-w-full flex-wrap"
      @update:model-value="emit('filter', $event as SourceFilter)"
    >
      <el-radio-button value="all">全部</el-radio-button>
      <el-radio-button value="shared">共用引用</el-radio-button>
      <el-radio-button value="independent">独立引用</el-radio-button>
      <el-radio-button value="unused">未使用</el-radio-button>
    </el-radio-group>
  </div>
</template>
