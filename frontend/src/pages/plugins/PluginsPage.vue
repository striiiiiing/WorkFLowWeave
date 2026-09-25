<script setup lang="ts">
import {
  useSystemDiagnostics,
  usePluginReload,
  PluginHealthPanel,
  PluginCatalog,
  PluginReloadActions,
} from '@/modules/system/public'
import PageHeader from '@/shared/ui/PageHeader.vue'
const diagnostics = useSystemDiagnostics()
const { plugins } = diagnostics
const action = usePluginReload(diagnostics.refresh)
</script>
<template>
  <PageHeader title="插件与能力" description="查看已注册的采集、通知和 Agent 工具及参数结构">
    <el-button
      :loading="plugins.pending.value || diagnostics.health.pending.value"
      @click="diagnostics.refresh"
    >
      刷新
    </el-button>
    <PluginReloadActions :action="action" />
  </PageHeader>
  <el-alert
    v-if="plugins.error.value"
    :title="plugins.error.value"
    type="error"
    :closable="false"
    show-icon
  />
  <el-alert
    v-if="action.error.value"
    :title="action.error.value"
    type="error"
    :closable="false"
    show-icon
  />
  <el-alert
    v-for="(error, index) in action.report.value?.errors"
    :key="index"
    :title="`${error.code}: ${error.message}`"
    type="warning"
    :closable="false"
  />
  <PluginCatalog
    :data="plugins.data.value"
    :pending="plugins.pending.value"
    :error="plugins.error.value"
  />
  <PluginHealthPanel :diagnostics="diagnostics" />
</template>
