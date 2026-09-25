<script setup lang="ts">
import type { SourceConfig } from '../model/types'
defineProps<{ source: SourceConfig }>()
</script>
<template>
  <dl class="source-summary">
    <div>
      <dt>采集器</dt>
      <dd>{{ source.collector }}</dd>
    </div>
    <div>
      <dt>状态</dt>
      <dd>{{ source.enabled ? '已启用' : '已停用' }}</dd>
    </div>
    <div v-if="source.options?.limit !== undefined">
      <dt>读取上限</dt>
      <dd>{{ source.options.limit }}</dd>
    </div>
    <div v-if="source.setters?.format">
      <dt>输出格式</dt>
      <dd>{{ source.setters.format }}</dd>
    </div>
    <div>
      <dt>超时</dt>
      <dd>{{ source.timeout }} 秒</dd>
    </div>
  </dl>
</template>
<style scoped>
.source-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 14px 28px;
  padding: 12px 16px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  font-size: 13px;
}
.source-summary div {
  display: flex;
  gap: 8px;
  min-width: 0;
}
dt {
  color: var(--el-text-color-secondary);
}
dd {
  overflow-wrap: anywhere;
}
</style>
