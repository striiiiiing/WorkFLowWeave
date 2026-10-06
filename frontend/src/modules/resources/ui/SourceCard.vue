<script setup lang="ts">
import type { SourceConfig, SourceUsageView } from '../model/public'
import { sourceName } from '../model/public'
import SourceSummary from './SourceSummary.vue'
import AppIcon from '@/shared/ui/icons/AppIcon.vue'
defineProps<{
  source: SourceConfig
  usages?: readonly SourceUsageView[]
  busy: boolean
  usagePending: boolean
}>()
const emit = defineEmits<{
  edit: [source: SourceConfig]
  remove: [id: string]
  enabled: [source: SourceConfig, enabled: boolean]
  workflow: [id: string]
}>()
</script>
<template>
  <el-card shadow="never">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="flex items-start gap-3 min-w-0">
        <AppIcon name="database" />
        <div class="min-w-0">
          <h2 class="font-semibold break-all">{{ sourceName(source) }}</h2>
          <p class="mono muted text-xs mt-1">{{ source.id }}</p>
          <p v-if="source.description" class="muted text-sm mt-2">{{ source.description }}</p>
        </div>
      </div>
      <el-switch
        :model-value="source.enabled"
        :disabled="busy"
        :aria-label="`${sourceName(source)} 启用状态`"
        active-text="已启用"
        inactive-text="已停用"
        @change="emit('enabled', source, Boolean($event))"
      />
    </div>
    <SourceSummary :source="source" class="mt-4" />
    <div class="mt-4 border-t pt-3">
      <div class="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
        <strong>使用位置</strong>
        <span v-if="usages === undefined" class="muted">
          {{ usagePending ? '正在读取工作流使用位置…' : '引用关系暂不可用' }}
        </span>
        <template v-else>
          <span class="muted">
            同步到 {{ usages.filter((item) => !item.detached).length }} 个工作流，{{
              usages.filter((item) => item.detached).length
            }}
            个独立引用
          </span>
          <el-button
            v-for="usage in usages"
            :key="usage.id"
            link
            @click="emit('workflow', usage.id)"
          >
            <el-tag :type="usage.detached ? 'warning' : 'success'" effect="plain">
              {{ usage.name }}{{ usage.detached ? ' · 独立' : ' · 共用' }}
            </el-tag>
          </el-button>
          <span v-if="!usages.length" class="muted">暂无工作流使用</span>
        </template>
      </div>
    </div>
    <div class="flex justify-end gap-2 mt-4">
      <el-button :disabled="usages === undefined || usagePending" @click="emit('edit', source)">
        编辑
      </el-button>
      <el-popconfirm title="确认删除此数据源？" @confirm="emit('remove', source.id)">
        <template #reference>
          <el-button type="danger" plain :disabled="busy">删除</el-button>
        </template>
      </el-popconfirm>
    </div>
  </el-card>
</template>
