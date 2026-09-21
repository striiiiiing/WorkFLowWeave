<script setup lang="ts">
import StatusBadge from './StatusBadge.vue'
import { formatTime, formatWorkflowName } from '@/domain/session'
import type { SessionRecord } from '@/types'
withDefaults(defineProps<{ sessions: SessionRecord[]; loading?: boolean }>(), { loading: false })
</script>
<template>
  <el-table v-loading="loading" :data="sessions" row-key="session_id" empty-text="暂无运行记录">
    <el-table-column label="Session ID" min-width="190">
      <template #default="{ row }">
        <router-link :to="`/runs/${row.session_id}`" class="mono">{{ row.session_id }}</router-link>
      </template>
    </el-table-column>
    <el-table-column label="工作流名称" min-width="160">
      <template #default="{ row }">{{ formatWorkflowName(row.workflow_name) }}</template>
    </el-table-column>
    <el-table-column prop="workflow_id" label="工作流 ID" min-width="160" />
    <el-table-column label="运行状态" width="110">
      <template #default="{ row }"><StatusBadge :status="row.status" /></template>
    </el-table-column>
    <el-table-column prop="stage" label="当前阶段" width="110" />
    <el-table-column label="创建时间" min-width="180">
      <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
    </el-table-column>
  </el-table>
</template>
