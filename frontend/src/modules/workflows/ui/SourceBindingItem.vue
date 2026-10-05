<script setup lang="ts">
import { SourceSummary, type SourceConfig, type SourceOverride } from '@/modules/resources/public'

defineProps<{
  sourceId: string
  index: number
  total: number
  source?: SourceConfig
  override?: SourceOverride
  sharedCount: number
  hasShared: boolean
  pending: boolean
  refreshing?: boolean
  restoreError?: string
}>()
const emit = defineEmits<{
  move: [delta: number]
  edit: []
  detach: []
  restore: []
  publish: []
  refresh: []
  remove: []
}>()
</script>

<template>
  <article class="source-card" :aria-label="`数据源 ${sourceId}`">
    <div class="source-card-heading">
      <div class="flex items-center gap-3 min-w-0 flex-wrap">
        <span class="source-index">{{ index + 1 }}</span>
        <h3 class="font-semibold break-all">
          {{ source?.display_name || sourceId }}
        </h3>
        <el-tag :type="override?.source ? 'warning' : 'success'" effect="plain">
          {{ override?.source ? '独立配置' : `全局同步 (${sharedCount})` }}
        </el-tag>
      </div>
      <div class="flex gap-1">
        <el-button :disabled="index === 0" @click="emit('move', -1)">上移</el-button>
        <el-button :disabled="index === total - 1" @click="emit('move', 1)">下移</el-button>
      </div>
    </div>

    <template v-if="source">
      <SourceSummary :source="source" />
      <el-alert
        v-if="source.enabled === false"
        title="此数据源已停用，本次运行不会采集；重新启用后会恢复原设置。"
        type="warning"
        :closable="false"
        class="mt-3"
      />
      <el-alert
        v-if="override?.source && !hasShared"
        title="资源中心中已不存在此来源，无法恢复共用配置；当前独立配置仍保留。"
        type="error"
        :closable="false"
        class="mt-3"
      />
      <el-alert
        v-if="restoreError"
        :title="restoreError"
        type="error"
        :closable="false"
        class="mt-3"
      />
      <div class="source-card-footer">
        <p class="muted text-xs">
          {{
            override?.source
              ? '独立配置不再接收资源中心的修改；保存工作流后生效。'
              : sharedCount > 1
                ? '多个工作流共用此数据源，单独修改请先脱离共用配置。'
                : '当前工作流是唯一共用位置，可直接保存数据源。'
          }}
        </p>
        <div class="flex flex-wrap gap-2">
          <el-button
            :disabled="!override?.source && (!!override || sharedCount > 1)"
            @click="emit('edit')"
          >
            编辑配置
          </el-button>
          <el-popconfirm
            v-if="override"
            title="恢复后放弃当前工作流的独立设置，使用资源中心的最新配置？"
            @confirm="emit('restore')"
          >
            <template #reference><el-button>恢复共用配置</el-button></template>
          </el-popconfirm>
          <el-button v-if="!override?.source" :loading="pending" @click="emit('detach')">
            脱离共用配置
          </el-button>
          <el-popconfirm
            v-else
            :title="`将此配置保存到资源中心，并同步到 ${sharedCount} 个共用工作流？`"
            @confirm="emit('publish')"
          >
            <template #reference>
              <el-button :loading="pending">保存为共用数据源</el-button>
            </template>
          </el-popconfirm>
          <el-button type="danger" plain @click="emit('remove')">移除</el-button>
        </div>
      </div>
    </template>
    <template v-else>
      <el-alert title="数据源不存在，请恢复资源或从工作流移除。" type="error" :closable="false" />
      <div class="flex flex-wrap gap-2 mt-3">
        <el-button :loading="refreshing" @click="emit('refresh')">重新加载资源目录</el-button>
        <el-button type="danger" @click="emit('remove')">移除</el-button>
      </div>
    </template>
  </article>
</template>

<style scoped>
.source-card {
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 16px;
}
.source-card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
}
.source-index {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border-radius: 6px;
  padding: 3px 9px;
  font-weight: 700;
}
.source-card-footer {
  border-top: 1px solid var(--el-border-color-lighter);
  margin-top: 16px;
  padding-top: 14px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
</style>
