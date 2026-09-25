<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useRunList, RUN_PAGE_SIZE, RunFilters, SessionTable } from '@/modules/runs/public'
import PageHeader from '@/shared/ui/PageHeader.vue'
const router = useRouter()
const {
  filterField,
  filterValue,
  filterStatus,
  filterAfter,
  filterBefore,
  page,
  data,
  pending,
  error,
  refresh,
  search,
  clearSearch,
} = useRunList()
function openRun(id: string) {
  void router.push({ name: 'run-detail', params: { id } })
}
</script>
<template>
  <PageHeader title="运行记录" description="按字段筛选执行历史与阶段产物">
    <el-button :loading="pending" @click="refresh">刷新</el-button>
  </PageHeader>
  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
  <el-card shadow="never">
    <RunFilters
      v-model:field="filterField"
      v-model:value="filterValue"
      v-model:status="filterStatus"
      v-model:after="filterAfter"
      v-model:before="filterBefore"
      @search="search"
      @reset="clearSearch"
    />
    <SessionTable :sessions="data ?? []" :loading="pending" @open="openRun" />
    <div class="flex justify-end items-center gap-3 mt-5">
      <el-button :disabled="page === 0 || pending" @click="page--">上一页</el-button>
      <span class="muted">第 {{ page + 1 }} 页</span>
      <el-button :disabled="pending || !data || data.length < RUN_PAGE_SIZE" @click="page++">
        下一页
      </el-button>
    </div>
  </el-card>
</template>
