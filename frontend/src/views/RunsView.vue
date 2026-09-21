<script setup lang="ts">
import { ref } from 'vue'
import { runsApi } from '@/api/runs'
import { useQuery } from '@/composables/useQuery'
import PageHeader from '@/components/common/PageHeader.vue'
import SessionTable from '@/components/common/SessionTable.vue'
import type { SessionQuery } from '@/api/runs'
import type { SessionStatus } from '@/types'
const PAGE_SIZE = 20
type FilterField = 'workflow_name' | 'workflow_id' | 'session_id' | 'status'
const filterField = ref<FilterField>('workflow_name')
const filterValue = ref('')
const filter = ref<{ field: FilterField; value: string }>({ field: 'workflow_name', value: '' })
const page = ref(0)
const { data, pending, error, refresh } = useQuery(
  (signal) => {
    const query: SessionQuery = {
      offset: page.value * PAGE_SIZE,
      limit: PAGE_SIZE,
      [filter.value.field]: filter.value.value || undefined,
    }
    return runsApi.list(query, signal)
  },
  [page, filter],
)
function search() {
  const next = { field: filterField.value, value: filterValue.value.trim() }
  if (page.value === 0 && filter.value.field === next.field && filter.value.value === next.value) {
    void refresh()
    return
  }
  page.value = 0
  filter.value = next
}
function clearSearch() {
  filterValue.value = ''
  search()
}
const statusOptions: Array<{ value: SessionStatus; label: string }> = [
  { value: 'created', label: '等待执行' },
  { value: 'running', label: '运行中' },
  { value: 'completed', label: '已完成' },
  { value: 'partial', label: '部分完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
  { value: 'interrupted', label: '已中断' },
]
</script>
<template>
  <PageHeader title="运行记录" description="按工作流查询执行历史与阶段产物">
    <el-button :loading="pending" @click="refresh">刷新</el-button>
  </PageHeader>
  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
  <el-card shadow="never">
    <form class="flex gap-3 mb-5" @submit.prevent="search">
      <el-select v-model="filterField" aria-label="筛选字段" class="w-44">
        <el-option label="工作流名称" value="workflow_name" />
        <el-option label="工作流 ID" value="workflow_id" />
        <el-option label="Session ID" value="session_id" />
        <el-option label="运行状态" value="status" />
      </el-select>
      <el-select
        v-if="filterField === 'status'"
        v-model="filterValue"
        aria-label="运行状态"
        placeholder="选择状态"
        clearable
        class="min-w-44"
      >
        <el-option v-for="option in statusOptions" :key="option.value" v-bind="option" />
      </el-select>
      <el-input
        v-else
        v-model="filterValue"
        :aria-label="`按${filterField === 'workflow_name' ? '工作流名称' : filterField === 'workflow_id' ? '工作流 ID' : 'Session ID'}筛选`"
        :placeholder="filterField === 'workflow_name' ? '输入工作流名称' : filterField === 'workflow_id' ? '输入工作流 ID' : '输入 Session ID'"
        clearable
      />
      <el-button native-type="submit">筛选</el-button>
      <el-button v-if="filter.value.value" type="info" plain @click="clearSearch">清除</el-button>
    </form>
    <SessionTable :sessions="data ?? []" :loading="pending" />
    <div class="flex justify-end items-center gap-3 mt-5">
      <el-button :disabled="page === 0 || pending" @click="page--">上一页</el-button>
      <span class="muted">第 {{ page + 1 }} 页</span>
      <el-button :disabled="pending || !data || data.length < PAGE_SIZE" @click="page++">
        下一页
      </el-button>
    </div>
  </el-card>
</template>
