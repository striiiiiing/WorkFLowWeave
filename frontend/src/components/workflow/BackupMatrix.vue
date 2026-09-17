<template>
  <!-- [Design Decision DEC-LAYOUT-01] 垂直流式阶梯编排卡片：备份与持久化策略 -->
  <Card
    title="阶段 5：持久化与备份策略 (Backup Policy)"
    subtitle="控制 Session 业务正文（快照、采集输入、分析结果、最终结果）的持久化存储与过期保留"
    icon="database"
  >
    <div class="space-y-4">
      <!-- 总开关 -->
      <div class="flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-900/50 rounded-lg border border-slate-200/60 dark:border-slate-700/60">
        <div>
          <span class="text-sm font-semibold text-slate-800 dark:text-slate-200">启用正文持久化备份 (enabled)</span>
          <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            关闭时执行过程中的大正文仅保留在当前内存上下文中，不可用于历史回溯与恢复
          </p>
        </div>
        <Switch v-model="policy.enabled" />
      </div>

      <!-- 细分开关矩阵 -->
      <div v-if="policy.enabled" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 p-4 bg-white dark:bg-slate-800/90 rounded-lg border border-slate-200 dark:border-slate-700">
        <Switch v-model="policy.snapshot" label="备份配置快照 (snapshot)" />
        <Switch v-model="policy.collection" label="备份采集共享输入 (collection)" />
        <Switch v-model="policy.analysis" label="备份分析分支结果 (analysis)" />
        <Switch v-model="policy.final" label="备份最终冻结输出 (final)" />
      </div>

      <!-- 失败策略与保留天数 -->
      <div v-if="policy.enabled" class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label class="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
            正文备份写入失败策略 (on_failure)
          </label>
          <select
            v-model="policy.on_failure"
            class="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 min-h-[44px]"
          >
            <option value="stop">stop (备份失败立即终止任务，防止未持久化)</option>
            <option value="continue">continue (报告备份降级并继续执行后续流程)</option>
          </select>
        </div>

        <div>
          <label class="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
            正文自动保留天数 (retention_days)
          </label>
          <input
            v-model.number="retentionDaysModel"
            type="number"
            min="1"
            placeholder="留空表示永久保留"
            class="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 min-h-[44px]"
          />
        </div>
      </div>
    </div>
  </Card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Card from '@/components/common/Card.vue'
import Switch from '@/components/common/Switch.vue'
import type { BackupPolicy } from '@/types'

const props = defineProps<{
  policy: BackupPolicy
}>()

const retentionDaysModel = computed({
  get: () => props.policy.retention_days ?? '',
  set: (val: string | number) => {
    if (val === '' || val === null || isNaN(Number(val))) {
      props.policy.retention_days = null
    } else {
      props.policy.retention_days = Math.max(1, Number(val))
    }
  }
})
</script>
