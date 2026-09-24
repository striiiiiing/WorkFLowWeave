<script setup lang="ts">
import { resourcesApi } from '@/api/resources'
import { useQuery } from '@/shared/async/useQuery'
import ResourceEditor from './ResourceEditor.vue'
import type { SourceConfig, SourceOverride } from '@/types'
import type { EditableResource } from '@/domain/resources'

const props = defineProps<{
  initial?: SourceConfig
  override?: SourceOverride
  local?: boolean
  linkedCount?: number
}>()
const emit = defineEmits<{ saved: [value: SourceConfig]; cancel: [] }>()
const { data, pending, error, refresh } = useQuery(async (signal) =>
  props.initial ? resourcesApi.resolveSource(props.initial.id, props.override, signal) : null,
)
function saved(value?: EditableResource) {
  if (value && 'collector' in value) emit('saved', value)
}
</script>

<template>
  <el-drawer
    :model-value="true"
    :title="!initial ? '新增数据源' : local ? '编辑独立配置' : '编辑共用数据源'"
    size="min(94vw, 760px)"
    append-to-body
    destroy-on-close
    @close="emit('cancel')"
  >
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-button v-if="error" @click="refresh">重新加载数据源</el-button>
    <el-skeleton v-if="pending" :rows="8" animated />
    <template v-else-if="data !== undefined && !error">
      <el-alert
        class="mb-5"
        :title="
          local
            ? '仅修改当前工作流的独立配置，保存工作流后生效。'
            : initial
              ? `保存后同步到 ${linkedCount ?? 0} 个使用共用配置的工作流，已脱离的工作流不受影响。`
              : '保存后加入资源配置中心，可在多个工作流中使用。'
        "
        type="info"
        :closable="false"
        show-icon
      />
      <ResourceEditor
        kind="sources"
        :initial="data ?? undefined"
        :local="local"
        @saved="saved"
        @cancel="emit('cancel')"
      />
    </template>
  </el-drawer>
</template>
