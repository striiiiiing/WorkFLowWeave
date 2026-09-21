<script setup lang="ts">
import StatusBadge from './StatusBadge.vue'
import { formatTime, formatWorkflowName, stages } from '@/domain/session'
import type { SessionRecord } from '@/types'
withDefaults(defineProps<{ sessions: SessionRecord[]; loading?: boolean }>(), { loading: false })
function formatStage(stage: SessionRecord['stage']) {
  return stages.find((item) => item.key === stage)?.label ?? '尚未开始'
}
</script>
<template>
  <div class="hidden md:block">
    <el-table v-loading="loading" :data="sessions" row-key="session_id" empty-text="暂无运行记录">
      <el-table-column label="Session ID" min-width="190">
        <template #default="{ row }">
          <router-link :to="`/runs/${row.session_id}`" class="mono">
            {{ row.session_id }}
          </router-link>
        </template>
      </el-table-column>
      <el-table-column label="工作流名称" min-width="160">
        <template #default="{ row }">{{ formatWorkflowName(row.workflow_name) }}</template>
      </el-table-column>
      <el-table-column prop="workflow_id" label="工作流 ID" min-width="160" />
      <el-table-column label="运行状态" width="110">
        <template #default="{ row }"><StatusBadge :status="row.status" /></template>
      </el-table-column>
      <el-table-column label="当前阶段" min-width="145">
        <template #default="{ row }">{{ formatStage(row.stage) }}</template>
      </el-table-column>
      <el-table-column label="创建时间" min-width="180">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
    </el-table>
  </div>
  <div v-if="!loading && sessions.length === 0" class="md:hidden muted py-6 text-center">
    暂无运行记录
  </div>
  <div v-else class="md:hidden divide-y">
    <p v-if="loading" role="status" class="muted py-2">正在读取运行记录…</p>
    <article v-for="row in sessions" :key="row.session_id" class="py-4 first:pt-0 last:pb-0">
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0">
          <p class="font-medium truncate">{{ formatWorkflowName(row.workflow_name) }}</p>
          <p class="muted text-sm mt-1">{{ formatTime(row.created_at) }}</p>
        </div>
        <StatusBadge :status="row.status" />
      </div>
      <p class="muted text-sm mt-2">{{ formatStage(row.stage) }}</p>
      <router-link :to="`/runs/${row.session_id}`" class="inline-block mt-3">查看详情</router-link>
    </article>
  </div>
</template>
