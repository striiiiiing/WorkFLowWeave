<script setup lang="ts">
import { computed } from 'vue'
import type { SystemDiagnostics } from '../composables/useSystemDiagnostics'
import { staleMessage } from '@/shared/async/presentation'
import SectionCard from '@/shared/ui/SectionCard.vue'
const props = defineProps<{ diagnostics: SystemDiagnostics }>()
const plugins = computed(() => props.diagnostics.plugins.data.value)
const health = computed(() => props.diagnostics.health.data.value)
const pluginsError = computed(() => props.diagnostics.plugins.error.value)
const healthError = computed(() => props.diagnostics.health.error.value)
const pluginsPending = computed(() => props.diagnostics.plugins.pending.value)
const healthPending = computed(() => props.diagnostics.health.pending.value)
const pluginRows = computed(() => props.diagnostics.projection.value.rows)
</script>
<template>
  <SectionCard
    title="插件健康状态"
    class="mt-6"
    description="显示注册诊断与受影响资源，不代表远程服务连通性。"
  >
    <el-alert
      v-if="pluginsError"
      :title="staleMessage(pluginsError, !!plugins, diagnostics.plugins.readAt.value)"
      type="error"
      :closable="false"
      show-icon
      class="mb-4"
    />
    <el-alert
      v-if="healthError"
      :title="staleMessage(healthError, !!health, diagnostics.health.readAt.value)"
      type="warning"
      :closable="false"
      show-icon
      class="mb-4"
    />
    <el-alert
      v-if="diagnostics.projection.value.error"
      :title="diagnostics.projection.value.error"
      type="error"
      :closable="false"
    />
    <el-table v-if="pluginRows" :data="pluginRows" empty-text="暂无插件">
      <el-table-column prop="plugin" label="插件" />
      <el-table-column prop="kind" label="类型" />
      <el-table-column label="已注册能力">
        <template #default="{ row }">{{ row.capabilities.join('、') || '—' }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" />
      <el-table-column label="诊断与受影响资源" min-width="280">
        <template #default="{ row }">
          <span>{{ row.errors.join('；') || '—' }}</span>
          <span v-if="row.affectedResources.length" class="block text-orange-600 mt-1">
            受影响资源：{{ row.affectedResources.join('、') }}
          </span>
        </template>
      </el-table-column>
    </el-table>
    <p v-else-if="plugins && healthError" class="muted py-4">
      已读取 {{ plugins.length }} 项注册能力，系统诊断暂时不可用。
    </p>
    <p v-else-if="pluginsPending || healthPending" class="muted py-4">正在读取插件诊断</p>
    <p v-else class="muted py-4">暂无插件诊断</p>
  </SectionCard>
</template>
