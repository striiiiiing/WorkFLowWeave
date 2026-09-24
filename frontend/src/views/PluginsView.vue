<script setup lang="ts">
import { computed, ref } from 'vue'
import { systemApi } from '@/api/system'
import { useQuery } from '@/shared/async/useQuery'
import { useAsyncTask } from '@/shared/async/useAsyncTask'
import type { CapabilityDescription } from '@/types'
import PageHeader from '@/shared/ui/PageHeader.vue'
const { data, pending, error, refresh } = useQuery((signal) => systemApi.plugins(signal))
const action = useAsyncTask()
const filter = ref('all')
const selected = ref<CapabilityDescription>()
const dialog = ref(false)
const filtered = computed(
  () => data.value?.filter((item) => filter.value === 'all' || item.kind === filter.value) ?? [],
)
function reload() {
  void action.run(async () => {
    const result = await systemApi.reload('plugins')
    await refresh()
    if (result.report?.errors.length)
      throw new Error(
        result.report.errors.map((item) => `${item.code}: ${item.message}`).join('；'),
      )
  })
}
function inspect(plugin: CapabilityDescription) {
  selected.value = plugin
  dialog.value = true
}
</script>
<template>
  <PageHeader title="插件与能力" description="查看已注册的采集、通知和 Agent 工具及参数结构">
    <el-button :loading="pending" @click="refresh">刷新</el-button>
    <el-button :loading="action.pending.value" @click="reload">重新加载插件</el-button>
  </PageHeader>
  <el-alert
    v-if="error || action.error.value"
    :title="error || action.error.value"
    type="error"
    :closable="false"
    show-icon
  />
  <el-radio-group v-model="filter" class="mb-6">
    <el-radio-button value="all">全部</el-radio-button>
    <el-radio-button value="collector">采集器</el-radio-button>
    <el-radio-button value="channel">通知渠道</el-radio-button>
    <el-radio-button value="tool">Agent 工具</el-radio-button>
  </el-radio-group>
  <div v-loading="pending" class="grid grid-cols-1 md:grid-cols-2 gap-5">
    <el-card v-for="plugin in filtered" :key="`${plugin.kind}/${plugin.name}`" shadow="hover">
      <template #header>
        <div class="flex justify-between gap-3">
          <h2 class="font-semibold">{{ plugin.name }}</h2>
          <el-tag>{{ plugin.kind }}</el-tag>
        </div>
      </template>
      <p class="muted mb-4">{{ plugin.description }}</p>
      <p class="mono muted text-xs">{{ plugin.plugin }}</p>
      <div class="flex flex-wrap gap-2 my-4">
        <el-tag v-for="capability in plugin.capabilities" :key="capability" type="info">
          {{ capability }}
        </el-tag>
      </div>
      <el-button @click="inspect(plugin)">查看参数结构</el-button>
    </el-card>
  </div>
  <el-empty v-if="!pending && !error && !filtered.length" description="暂无匹配的插件能力" />
  <el-dialog v-model="dialog" :title="selected?.name" width="760px">
    <template v-if="selected">
      <h3 class="font-semibold mb-3">参数 Schema</h3>
      <pre class="text-xs p-4 bg-slate-100 dark:bg-slate-900 rounded">{{
        JSON.stringify(selected.input_schema ?? selected.options_schema, null, 2)
      }}</pre>
      <template v-if="selected.setters_schema">
        <h3 class="font-semibold my-3">处理规则 Schema</h3>
        <pre class="text-xs p-4 bg-slate-100 dark:bg-slate-900 rounded">{{
          JSON.stringify(selected.setters_schema, null, 2)
        }}</pre>
      </template>
      <p class="muted mt-4">
        字段：{{ selected.fields.join('、') || '无' }} · 计数单位：{{
          selected.count_unit ?? '未声明'
        }}
      </p>
    </template>
  </el-dialog>
</template>
