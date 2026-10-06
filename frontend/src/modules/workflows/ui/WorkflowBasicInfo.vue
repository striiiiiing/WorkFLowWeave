<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import SectionCard from '@/shared/ui/SectionCard.vue'
import { useCronPreview } from '../composables/useCronPreview'
import type { WorkflowChanges } from '../model/create/actions'
import {
  DEFAULT_DAILY_CRON,
  dailyCron,
  hourlyCron,
  parseCronPreset,
  weekdays,
  weeklyCron,
  type CronPreset,
  type Weekday,
} from '../model/create/cronPresets'
import type { WorkflowDefinition, WorkflowSchedule } from '../model/public'

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
const cronMode = ref<CronPreset['mode']>('custom')
const preset = computed(() => parseCronPreset(cron.value?.expression ?? ''))
const mode = computed(() => (cron.value ? cronMode.value : (schedule.value?.type ?? 'manual')))
const cronTime = computed(() =>
  preset.value.mode === 'daily' || preset.value.mode === 'weekly'
    ? `${String(preset.value.hour).padStart(2, '0')}:${String(preset.value.minute).padStart(2, '0')}`
    : '',
)

watch(
  () => schedule.value?.type,
  () => {
    if (cron.value) cronMode.value = parseCronPreset(cron.value.expression).mode
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
  if (value === 'hourly' || value === 'daily' || value === 'weekly' || value === 'custom') {
    cronMode.value = value
    const expression =
      value === 'hourly'
        ? hourlyCron(0)
        : value === 'daily'
          ? DEFAULT_DAILY_CRON
          : value === 'weekly'
            ? weeklyCron('MON', 9, 0)
            : (cron.value?.expression ?? '')
    updateSchedule({
      type: 'cron',
      expression,
      timezone: null,
    })
  }
}
function setAt(value: Date | null) {
  if (schedule.value?.type !== 'at') return
  updateSchedule({ type: 'at', at: value instanceof Date ? value.toISOString() : '' })
}
function setCronExpression(expression: string) {
  if (!cron.value) return
  updateSchedule({
    ...cron.value,
    expression,
    timezone: expression === cron.value.expression ? cron.value.timezone : null,
  })
}
function setHourlyMinute(value: number | undefined) {
  if (
    cronMode.value !== 'hourly' ||
    typeof value !== 'number' ||
    !Number.isInteger(value) ||
    value < 0 ||
    value > 59
  )
    return
  setCronExpression(hourlyCron(value))
}
function setCronTime(value: string) {
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(value)) return
  const hour = Number(value.slice(0, 2))
  const minute = Number(value.slice(3, 5))
  if (cronMode.value === 'daily') setCronExpression(dailyCron(hour, minute))
  if (cronMode.value === 'weekly' && preset.value.mode === 'weekly')
    setCronExpression(weeklyCron(preset.value.day, hour, minute))
}
function setWeekday(day: Weekday) {
  if (cronMode.value !== 'weekly' || preset.value.mode !== 'weekly') return
  setCronExpression(weeklyCron(day, preset.value.hour, preset.value.minute))
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
          <el-option value="at" label="单次运行" />
          <el-option value="hourly" label="每小时" />
          <el-option value="daily" label="每天" />
          <el-option value="weekly" label="每周" />
          <el-option value="custom" label="自定义" />
          <el-option
            v-if="schedule?.type === 'every'"
            value="every"
            label="旧运行计划（只读）"
            disabled
          />
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
      <el-form-item v-if="schedule?.type === 'every'" label="原有计划">
        <span>每 {{ schedule.every_seconds }} 秒运行（只读）</span>
      </el-form-item>
      <el-form-item v-if="cron && mode === 'hourly'" label="每小时第几分钟">
        <el-input-number
          :model-value="preset.mode === 'hourly' ? preset.minute : undefined"
          :min="0"
          :max="59"
          :step="1"
          step-strictly
          @update:model-value="setHourlyMinute"
        />
      </el-form-item>
      <el-form-item v-if="cron && mode === 'weekly'" label="星期">
        <el-select
          :model-value="preset.mode === 'weekly' ? preset.day : undefined"
          @update:model-value="setWeekday"
        >
          <el-option
            v-for="day in weekdays"
            :key="day.value"
            :value="day.value"
            :label="day.label"
          />
        </el-select>
      </el-form-item>
      <el-form-item
        v-if="cron && (mode === 'daily' || mode === 'weekly')"
        :label="cron.timezone ? '运行时间（原有计划时区）' : '运行时间（运行机器本地时区）'"
      >
        <el-input type="time" :model-value="cronTime" @update:model-value="setCronTime" />
      </el-form-item>
      <el-form-item
        v-if="cron && mode === 'custom'"
        label="Cron 表达式（分 时 日 月 周）"
        prop="schedule.expression"
        :rules="[{ required: true, message: '请输入 Cron 表达式' }, { validator: validateCron }]"
      >
        <el-input
          :model-value="cron.expression"
          placeholder="0 9 * * *"
          @update:model-value="setCronExpression($event)"
        />
      </el-form-item>
    </div>
    <div v-if="cron" aria-live="polite">
      <p v-if="cron.timezone === null" class="text-sm muted mb-1">运行机器本地时区（不指定）</p>
      <p v-else class="text-sm muted mb-1">
        原有计划时区：{{ cron.timezone }}（只读；修改计划后改用运行机器本地时区）
      </p>
      <el-alert v-if="previewError" :title="previewError" type="error" :closable="false" />
      <span v-else-if="previewPending">正在计算下一次运行时间…</span>
      <div v-else-if="preview" class="text-sm leading-6">
        <div>{{ preview.description }}</div>
        <div>实际采用时区：{{ preview.timezone }}</div>
        <div>下一次运行：{{ nextRun }}</div>
      </div>
    </div>
    <el-form-item label="系统提示词">
      <div class="prompt-field">
        <el-input
          :model-value="draft.system_prompt"
          type="textarea"
          :rows="3"
          @update:model-value="emit('update', { system_prompt: $event })"
        />
        <span class="prompt-hint">并行 AI 分析和汇聚汇总环节共用，在高级模式下可设置覆盖</span>
      </div>
    </el-form-item>
    <el-form-item v-if="advanced" label="输入模板">
      <el-input
        :model-value="draft.input_prompt"
        type="textarea"
        :rows="3"
        @update:model-value="emit('update', { input_prompt: $event })"
      />
    </el-form-item>
  </SectionCard>
</template>

<style scoped>
.prompt-field {
  width: 100%;
}
.prompt-hint {
  display: block;
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}
</style>
