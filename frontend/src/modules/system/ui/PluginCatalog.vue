<script setup lang="ts">
import { computed, ref } from 'vue'
import type { CapabilityDescription } from '../model/types'
import type { PluginHealth } from '../model/pluginHealth'
const props = defineProps<{
  data?: CapabilityDescription[]
  pending: boolean
  error: string
  health?: PluginHealth[]
}>()
const filter = ref('all')
const selected = ref<CapabilityDescription>()
const dialog = ref(false)
const filtered = computed(
  () => props.data?.filter((item) => filter.value === 'all' || item.kind === filter.value) ?? [],
)
function diagnostic(plugin: CapabilityDescription) {
  return props.health?.find((row) => row.plugin === plugin.plugin && row.kind === plugin.kind)
}
const unassigned = computed(
  () =>
    props.health?.filter(
      (row) =>
        !props.data?.some((plugin) => plugin.plugin === row.plugin && plugin.kind === row.kind),
    ) ?? [],
)
function inspect(plugin: CapabilityDescription) {
  selected.value = plugin
  dialog.value = true
}
</script>
<template>
  <el-radio-group v-model="filter" class="mb-6">
    <el-radio-button value="all">全部</el-radio-button>
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
      <section :aria-label="`${plugin.name} 健康状态`" class="mt-3">
        <el-tag :type="diagnostic(plugin)?.errors.length ? 'danger' : 'info'">
          {{ diagnostic(plugin)?.status ?? '待确认' }}
        </el-tag>
        <p
          v-for="message in diagnostic(plugin)?.errors"
          :key="message"
          class="text-red-700 dark:text-red-300 mt-2"
          role="alert"
        >
          {{ message }}
        </p>
      </section>
      <div class="flex flex-wrap gap-2 my-4">
        <el-tag v-for="capability in plugin.capabilities" :key="capability" type="info">
          {{ capability }}
        </el-tag>
      </div>
      <el-button @click="inspect(plugin)">查看参数结构</el-button>
    </el-card>
  </div>
  <el-alert
    v-for="row in unassigned"
    :key="`${row.kind}/${row.plugin}`"
    :title="`${row.plugin}: ${row.errors.join('；') || row.status}`"
    type="error"
    :closable="false"
  />
  <el-empty v-if="!pending && !error && !filtered.length" description="暂无匹配的插件能力" />
  <el-dialog v-model="dialog" :title="selected?.name" width="760px">
    <template v-if="selected">
      <h3 class="font-semibold mb-3">参数 Schema</h3>
      <pre class="text-xs p-4 bg-slate-100 dark:bg-slate-900 rounded">{{
        JSON.stringify(selected.input_schema ?? selected.options_schema, null, 2)
      }}</pre>
    </template>
  </el-dialog>
</template>
