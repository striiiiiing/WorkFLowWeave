<script setup lang="ts">
import { ref } from 'vue'
import { runsApi } from '@/api/runs'
import { useQuery } from '@/composables/useQuery'
import PageHeader from '@/components/common/PageHeader.vue'
import SessionTable from '@/components/common/SessionTable.vue'
const PAGE_SIZE = 20
const workflowId = ref('')
const filter = ref('')
const page = ref(0)
const { data, pending, error, refresh } = useQuery(
  (signal) =>
    runsApi.list(
      { workflow_id: filter.value, offset: page.value * PAGE_SIZE, limit: PAGE_SIZE },
      signal,
    ),
  [page, filter],
)
function search() {
  const next = workflowId.value.trim()
  if (page.value === 0 && filter.value === next) {
    void refresh()
    return
  }
  page.value = 0
  filter.value = next
}
</script>
<template>
  <PageHeader title="运行记录" description="按工作流查询执行历史与阶段产物">
    <el-button :loading="pending" @click="refresh">刷新</el-button>
  </PageHeader>
  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
  <el-card shadow="never">
    <form class="flex gap-3 mb-5" @submit.prevent="search">
      <el-input
        v-model="workflowId"
        aria-label="工作流 ID"
        placeholder="按工作流 ID 筛选"
        clearable
      />
      <el-button native-type="submit">查询</el-button>
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
