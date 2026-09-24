<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { runsApi, type SessionQuery } from '@/api/runs'
import { useQuery } from '@/shared/async/useQuery'
import { sessionStates } from '@/domain/session'
import PageHeader from '@/shared/ui/PageHeader.vue'
import SessionTable from '@/components/common/SessionTable.vue'
import type { SessionStatus } from '@/types'
const PAGE_SIZE = 20
const fields = [
  { value: 'workflow_name', label: '工作流名称', placeholder: '输入名称关键词（包含匹配）' },
  { value: 'workflow_id', label: '工作流 ID', placeholder: '输入完整工作流 ID' },
  { value: 'session_id', label: 'Session ID', placeholder: '输入完整 Session ID' },
  { value: 'status', label: '运行状态', placeholder: '选择运行状态' },
] as const
type FilterField = (typeof fields)[number]['value']
const filterField = ref<FilterField>('workflow_name')
const filterValue = ref('')
const filterStatus = ref<SessionStatus | ''>('')
const filterAfter = ref('')
const filterBefore = ref('')
const selectedField = computed(() => fields.find((field) => field.value === filterField.value)!)
const filter = ref<SessionQuery>({})
const page = ref(0)
const { data, pending, error, refresh } = useQuery(
  (signal) =>
    runsApi.list({ ...filter.value, offset: page.value * PAGE_SIZE, limit: PAGE_SIZE }, signal),
  [page, filter],
)
watch(filterField, resetDraft)
function resetDraft() {
  filterValue.value = ''
  filterStatus.value = ''
}
function search() {
  page.value = 0
  const fieldFilter =
    filterField.value === 'status'
      ? { status: filterStatus.value || undefined }
      : { [filterField.value]: filterValue.value.trim() || undefined }
  const nextFilter: SessionQuery = { ...fieldFilter }
  const after = toIsoDate(filterAfter.value)
  const before = toIsoDate(filterBefore.value)
  if (after) nextFilter.after = after
  if (before) nextFilter.before = before
  filter.value = nextFilter
}
function clearSearch() {
  resetDraft()
  filterAfter.value = ''
  filterBefore.value = ''
  page.value = 0
  filter.value = {}
}

function toIsoDate(value: string) {
  if (!value) return undefined
  const date = new Date(value)
  return date.toISOString()
}
</script>
<template>
  <PageHeader title="运行记录" description="按字段筛选执行历史与阶段产物">
    <el-button :loading="pending" @click="refresh">刷新</el-button>
  </PageHeader>
  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
  <el-card shadow="never">
    <form
      class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 mb-5"
      @submit.prevent="search"
    >
      <el-select v-model="filterField" aria-label="筛选字段" class="w-full">
        <el-option
          v-for="field in fields"
          :key="field.value"
          :label="field.label"
          :value="field.value"
        />
      </el-select>
      <el-select
        v-if="filterField === 'status'"
        v-model="filterStatus"
        aria-label="运行状态"
        placeholder="选择状态"
        clearable
        class="min-w-0"
      >
        <el-option
          v-for="(state, value) in sessionStates"
          :key="value"
          :label="state.label"
          :value="value"
        />
      </el-select>
      <el-input
        v-else
        v-model="filterValue"
        :aria-label="selectedField.label"
        :placeholder="selectedField.placeholder"
        clearable
      />
      <label class="flex items-center gap-2 min-w-0">
        <span class="muted whitespace-nowrap">开始时间</span>
        <input
          v-model="filterAfter"
          type="datetime-local"
          aria-label="开始时间"
          class="el-input__wrapper w-full min-w-0"
        />
      </label>
      <label class="flex items-center gap-2 min-w-0">
        <span class="muted whitespace-nowrap">结束时间</span>
        <input
          v-model="filterBefore"
          type="datetime-local"
          aria-label="结束时间"
          class="el-input__wrapper w-full min-w-0"
        />
      </label>
      <div class="flex shrink-0">
        <el-button native-type="submit" type="primary">筛选</el-button>
        <el-button @click="clearSearch">重置</el-button>
      </div>
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
