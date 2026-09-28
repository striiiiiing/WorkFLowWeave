<script setup lang="ts">
import type { SourceConfig } from '../model/types'
defineProps<{ source: SourceConfig }>()
</script>
<template>
  <dl class="source-summary">
    <div>
      <dt>调用</dt>
      <dd>
        {{
          source.call.kind === 'mcp'
            ? `${source.call.server} / ${source.call.tool}`
            : source.call.mode === 'argv'
              ? source.call.executable
              : source.call.command
        }}
      </dd>
    </div>
    <div>
      <dt>状态</dt>
      <dd>{{ source.enabled ? '已启用' : '已停用' }}</dd>
    </div>
    <div v-if="source.limits.item_tokens">
      <dt>单项 token</dt>
      <dd>{{ source.limits.item_tokens }}</dd>
    </div>
    <div v-if="source.limits.field_tokens">
      <dt>字段 token</dt>
      <dd>{{ source.limits.field_tokens }}</dd>
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
