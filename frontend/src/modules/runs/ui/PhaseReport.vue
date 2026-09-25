<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { useAsyncTask } from '@/shared/async/useAsyncTask'
import { resultStatus, unavailableText } from '../model/report'
import type { PhaseReportController } from '../composables/usePhaseReport'
import ReportText from '@/shared/ui/ReportText.vue'
import PluginReport from './PluginReport.vue'
const props = defineProps<{ report: PhaseReportController; active: boolean; advanced: boolean }>()
const copyTask = useAsyncTask()
function copy() {
  void copyTask.run(async () => {
    await navigator.clipboard.writeText(props.report.raw.value ?? '')
    ElMessage.success('已复制 JSON')
  })
}
</script>
<template>
  <div class="space-y-3 min-w-0">
    <el-skeleton v-if="report.pending.value && !report.data.value" :rows="3" animated />
    <div v-if="report.error.value" role="alert">
      <p class="text-red-700">{{ report.error.value }}</p>
      <el-button size="small" class="mt-2" @click="report.refresh">重新读取</el-button>
    </div>
    <template v-if="report.data.value">
      <p v-if="report.data.value.availability !== 'available'" class="muted">
        {{ unavailableText(report.data.value.availability, active) }}
      </p>
      <el-alert
        v-if="report.data.value.error"
        :title="report.data.value.error.message"
        type="error"
        :closable="false"
      />
      <el-alert
        v-if="report.parsed.value?.error"
        :title="report.parsed.value.error"
        type="error"
        :closable="false"
      />
      <template v-if="report.parsed.value?.result">
        <el-alert
          v-for="(message, index) in report.parsed.value.result.errors"
          :key="index"
          :title="message"
          type="warning"
          :closable="false"
        />
        <p v-if="!report.parsed.value.result.items.length" class="muted">
          {{
            report.identity.value?.stage === 'notify'
              ? '没有通知回执。'
              : report.identity.value?.stage === 'aggregate'
                ? '本次运行没有生成最终报告。'
                : '此阶段没有结果。'
          }}
        </p>
        <article
          v-for="(item, index) in report.parsed.value.result.items"
          :key="`${item.id}:${item.output ?? index}`"
          class="rounded-lg border border-slate-200 dark:border-slate-700 p-4 min-w-0"
        >
          <div class="flex flex-wrap items-center justify-between gap-2 mb-2">
            <h3 class="font-semibold break-all">
              {{
                item.id === 'final' && report.identity.value?.stage === 'aggregate'
                  ? '汇总报告'
                  : item.id
              }}
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
              {{ resultStatus(item.status, report.identity.value!.stage) }}
              <span v-if="item.count !== undefined">· 采集数量 {{ item.count }}</span>
            </span>
          </div>
          <p v-if="item.error" class="text-red-700 mb-2" role="alert">{{ item.error }}</p>
          <PluginReport v-if="item.sections?.length" :sections="item.sections" />
          <ReportText v-else-if="item.text" :text="item.text" />
          <details v-if="item.sections?.length && item.text" class="mt-3">
            <summary class="report-disclosure muted">查看提供给分析的正文</summary>
            <ReportText :text="item.text" />
          </details>
        </article>
      </template>
      <details v-if="advanced && report.data.value.availability === 'available'" class="mt-4">
        <summary class="report-disclosure">
          原始 JSON · 版本 {{ report.identity.value?.version }}
        </summary>
        <el-button size="small" class="my-2" :loading="copyTask.pending.value" @click="copy">
          复制 JSON
        </el-button>
        <p v-if="copyTask.error.value" class="text-red-700" role="alert">
          {{ copyTask.error.value }}
        </p>
        <pre class="bg-slate-900 text-slate-100 p-4 rounded-lg overflow-auto max-h-96 text-xs">{{
          report.raw.value
        }}</pre>
      </details>
    </template>
  </div>
</template>
