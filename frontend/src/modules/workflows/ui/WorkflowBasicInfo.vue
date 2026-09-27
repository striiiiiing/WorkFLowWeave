<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import SectionCard from '@/shared/ui/SectionCard.vue'
import { useCronPreview } from '../composables/useCronPreview'
import type { WorkflowChanges } from '../model/actions'
import type { WorkflowDefinition, WorkflowSchedule } from '../model/types'

const props = defineProps<{
  draft: WorkflowDefinition
  editing: boolean
  advanced: boolean
}>()
const emit = defineEmits<{
  update: [changes: WorkflowChanges]
  'update:advanced': [value: boolean]
}>()
const schedule = computed(() => props.draft.schedule)
const cron = computed(() => (schedule.value?.type === 'cron' ? schedule.value : null))
const { preview, pending: previewPending, error: previewError, nextRun } = useCronPreview(cron)
const mode = computed(() => schedule.value?.type ?? 'manual')
const everyUnit = ref(1)
const units = [
  { label: '秒', value: 1 },
  { label: '分钟', value: 60 },
  { label: '小时', value: 3600 },
  { label: '天', value: 86400 },
]
const localTimezoneOption = '__machine_local__'
const timezones = ['UTC', 'Asia/Shanghai', 'Asia/Tokyo', 'Europe/London', 'America/New_York']
const everyValue = computed(() =>
  schedule.value?.type === 'every' ? schedule.value.every_seconds / everyUnit.value : undefined,
)

watch(
  mode,
  (value) => {
    if (value !== 'every' || schedule.value?.type !== 'every') return
    const seconds = schedule.value.every_seconds
    everyUnit.value = [86400, 3600, 60].find((unit) => seconds >= unit && seconds % unit === 0) ?? 1
  },
  { immediate: true },
)

function updateSchedule(value: WorkflowSchedule) {
  emit('update', { schedule: value })
}
function changeMode(value: string) {
  if (value === mode.value) return
  if (value === 'manual') emit('update', { schedule: null })
  if (value === 'at') updateSchedule({ type: 'at', at: '' })
  if (value === 'every') updateSchedule({ type: 'every', every_seconds: 0 })
  if (value === 'cron') updateSchedule({ type: 'cron', expression: '', timezone: null })
}
function setAt(value: Date | null) {
  if (schedule.value?.type !== 'at') return
  updateSchedule({ type: 'at', at: value instanceof Date ? value.toISOString() : '' })
}
function setEvery(value: number | undefined) {
  if (schedule.value?.type !== 'every') return
  updateSchedule({ type: 'every', every_seconds: (value ?? 0) * everyUnit.value })
}
function setCron(changes: Partial<Extract<WorkflowSchedule, { type: 'cron' }>>) {
  if (!cron.value) return
  updateSchedule({ ...cron.value, ...changes })
}
function validatePositive(_rule: unknown, value: number, done: (error?: Error) => void) {
  done(Number.isFinite(value) && value > 0 ? undefined : new Error('请输入大于 0 的运行间隔'))
}
function validateCron(_rule: unknown, value: string, done: (error?: Error) => void) {
  done(value?.trim().split(/\s+/).length === 5 ? undefined : new Error('Cron 表达式需要五个字段'))
}
</script>

<template>
  <SectionCard title="基本信息与运行策略">
    <template #actions>
      <div class="flex items-center gap-3">
        <el-switch
          :model-value="draft.enabled"
          aria-label="启用工作流"
          active-text="启用工作流"
          @update:model-value="emit('update', { enabled: Boolean($event) })"
        />
        <el-switch
          :model-value="advanced"
          aria-label="高级模式"
          active-text="高级模式"
          @update:model-value="emit('update:advanced', Boolean($event))"
        />
      </div>
    </template>
    <div class="form-grid">
      <el-form-item label="工作流 ID">
        <el-input
          :model-value="draft.id"
          :disabled="editing"
          @update:model-value="emit('update', { id: $event })"
        />
      </el-form-item>
      <el-form-item label="显示名称">
        <el-input
          :model-value="draft.name"
          @update:model-value="emit('update', { name: $event })"
        />
      </el-form-item>
      <el-form-item label="运行计划">
        <el-select :model-value="mode" @update:model-value="changeMode">
          <el-option value="manual" label="仅手动运行" />
          <el-option value="at" label="指定时间运行一次" />
          <el-option value="every" label="固定间隔运行" />
          <el-option value="cron" label="Cron 定时运行" />
        </el-select>
      </el-form-item>
      <el-form-item
        v-if="schedule?.type === 'at'"
        label="运行时间（浏览器本地时间）"
        prop="schedule.at"
        :rules="{ required: true, message: '请选择运行时间' }"
      >
        <el-date-picker
          type="datetime"
          :model-value="schedule.at ? new Date(schedule.at) : undefined"
          @update:model-value="setAt"
        />
      </el-form-item>
      <el-form-item
        v-if="schedule?.type === 'every'"
        label="运行间隔"
        prop="schedule.every_seconds"
        :rules="{ validator: validatePositive }"
      >
        <div class="flex w-full gap-2">
          <el-input-number
            class="flex-1"
            :model-value="everyValue"
            :min="0"
            @update:model-value="setEvery"
          />
          <el-select class="w-28" :model-value="everyUnit" @update:model-value="everyUnit = $event">
            <el-option
              v-for="unit in units"
              :key="unit.value"
              :value="unit.value"
              :label="unit.label"
            />
          </el-select>
        </div>
      </el-form-item>
      <el-form-item
        v-if="cron"
        label="Cron 表达式（分 时 日 月 周）"
        prop="schedule.expression"
        :rules="[{ required: true, message: '请输入 Cron 表达式' }, { validator: validateCron }]"
      >
        <el-input
          :model-value="cron.expression"
          placeholder="0 9 * * *"
          @update:model-value="setCron({ expression: $event })"
        />
      </el-form-item>
      <el-form-item v-if="cron" label="计划时区（IANA）">
        <div class="w-full">
          <el-select
            :model-value="cron.timezone ?? localTimezoneOption"
            filterable
            allow-create
            default-first-option
            @update:model-value="
              setCron({ timezone: $event === localTimezoneOption ? null : $event })
            "
          >
            <el-option :value="localTimezoneOption" label="运行机器本地时区（不指定）" />
            <el-option v-for="zone in timezones" :key="zone" :value="zone" :label="zone" />
            <el-option
              v-if="cron.timezone && !timezones.includes(cron.timezone)"
              :value="cron.timezone"
              :label="cron.timezone"
            />
          </el-select>
          <p v-if="cron.timezone === null" class="text-xs muted mt-1">运行机器本地时区（未指定）</p>
        </div>
      </el-form-item>
    </div>
    <div v-if="cron" aria-live="polite">
      <el-alert v-if="previewError" :title="previewError" type="error" :closable="false" />
      <span v-else-if="previewPending">正在计算下一次运行时间…</span>
      <div v-else-if="preview" class="text-sm leading-6">
        <div>{{ preview.description }}</div>
        <div>实际采用时区：{{ preview.timezone }}</div>
        <div>下一次运行：{{ nextRun }}</div>
      </div>
    </div>
  </SectionCard>
</template>
