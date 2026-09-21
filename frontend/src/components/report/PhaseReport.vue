<script setup lang="ts">
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { runsApi } from '@/api/runs'
import { useQuery } from '@/composables/useQuery'
import { useAsyncTask } from '@/composables/useAsyncTask'
import { parsePhase, resultStatus, unavailableText } from '@/domain/report'
import type { WorkflowStage } from '@/types'
import ReportText from './ReportText.vue'
import PluginReport from './PluginReport.vue'
const props = defineProps<{
  id: string
  version: number
  stage: WorkflowStage
  active: boolean
  advanced: boolean
}>()
const query = useQuery(
  (signal) => runsApi.phase(props.id, props.stage, props.version, signal),
  [() => props.id, () => props.version, () => props.stage],
)
const parsed = computed(() => {
  if (query.data.value?.availability !== 'available') return undefined
  try {
    return { result: parsePhase(props.stage, query.data.value.content), error: '' }
  } catch (cause) {
    return { result: undefined, error: cause instanceof Error ? cause.message : String(cause) }
  }
})
const raw = computed(() => JSON.stringify(query.data.value?.content, null, 2))
const copyTask = useAsyncTask()
function copy() {
  void copyTask.run(async () => {
    await navigator.clipboard.writeText(raw.value ?? '')
    ElMessage.success('已复制 JSON')
  })
}
</script>
<template>
  <div class="space-y-3 min-w-0">
    <el-skeleton v-if="query.pending.value && !query.data.value" :rows="3" animated />
    <div v-if="query.error.value" role="alert">
      <p class="text-red-700">{{ query.error.value }}</p>
      <el-button size="small" class="mt-2" @click="query.refresh">重新读取</el-button>
    </div>
    <template v-if="query.data.value">
      <p v-if="query.data.value.availability !== 'available'" class="muted">
        {{ unavailableText(query.data.value.availability, active) }}
      </p>
      <el-alert
        v-if="query.data.value.error"
        :title="query.data.value.error.message"
        type="error"
        :closable="false"
      />
      <el-alert v-if="parsed?.error" :title="parsed.error" type="error" :closable="false" />
      <template v-if="parsed?.result">
        <el-alert
          v-for="(message, index) in parsed.result.errors"
          :key="index"
          :title="message"
          type="warning"
          :closable="false"
        />
        <p v-if="!parsed.result.items.length" class="muted">
          {{
            stage === 'notify'
              ? '没有通知回执。'
              : stage === 'aggregate'
                ? '本次运行没有生成最终报告。'
                : '此阶段没有结果。'
          }}
        </p>
        <article
          v-for="(item, index) in parsed.result.items"
          :key="`${item.id}:${item.output ?? index}`"
          class="rounded-lg border border-slate-200 dark:border-slate-700 p-4 min-w-0"
        >
          <div class="flex flex-wrap items-center justify-between gap-2 mb-2">
            <h3 class="font-semibold break-all">
              {{ item.id === 'final' && stage === 'aggregate' ? '汇总报告' : item.id }}
              <span v-if="item.output" class="font-normal">
                · {{ item.output === 'final' ? '汇总报告' : item.output }}
              </span>
            </h3>
            <span
              :class="
                ['failed', 'timeout', 'missing', 'uncertain'].includes(item.status)
                  ? 'text-red-700'
                  : 'text-slate-600 dark:text-slate-300'
              "
            >
              {{ resultStatus(item.status, stage) }}
              <span v-if="item.count !== undefined">· 采集数量 {{ item.count }}</span>
            </span>
          </div>
          <p v-if="item.error" class="text-red-700 mb-2" role="alert">{{ item.error }}</p>
          <PluginReport v-if="item.sections?.length" :sections="item.sections" />
          <ReportText v-else-if="item.text" :text="item.text" />
          <details v-if="item.sections?.length && item.text" class="mt-3">
            <summary class="cursor-pointer muted">查看提供给分析的正文</summary>
            <ReportText :text="item.text" />
          </details>
        </article>
      </template>
      <details v-if="advanced && query.data.value.availability === 'available'" class="mt-4">
        <summary class="cursor-pointer">原始 JSON · 版本 {{ version }}</summary>
        <el-button size="small" class="my-2" :loading="copyTask.pending.value" @click="copy">
          复制 JSON
        </el-button>
        <p v-if="copyTask.error.value" class="text-red-700" role="alert">
          {{ copyTask.error.value }}
        </p>
        <pre class="bg-slate-900 text-slate-100 p-4 rounded-lg overflow-auto max-h-96 text-xs">{{
          raw
        }}</pre>
      </details>
    </template>
  </div>
</template>
