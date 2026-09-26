<script setup lang="ts">
import { computed } from 'vue'
import { ElMessageBox } from 'element-plus'
import type { WorkflowChanges } from '../model/actions'
import type { WorkflowDefinition } from '../model/types'
import SectionCard from '@/shared/ui/SectionCard.vue'

const props = defineProps<{
  draft: WorkflowDefinition
  editing: boolean
}>()
const emit = defineEmits<{ update: [changes: WorkflowChanges] }>()
const schedule = computed(() =>
  props.draft.interval_seconds != null ? 'legacy' : props.draft.cron != null ? 'cron' : 'manual',
)
const timezones = computed(() => [...new Set(['UTC', 'Asia/Shanghai', props.draft.cron_timezone])])
async function changeSchedule(value: string) {
  if (schedule.value === 'legacy') {
    try {
      await ElMessageBox.confirm('替换旧版秒间隔计划后，将按所选运行计划调度。', '替换运行计划', {
        confirmButtonText: '替换',
        cancelButtonText: '保留原计划',
        type: 'warning',
      })
    } catch (action) {
      if (action === 'cancel' || action === 'close') return
      throw action
    }
  }
  emit('update', { interval_seconds: null, cron: value === 'cron' ? '' : null })
}
function validateCron(_rule: unknown, value: string, done: (error?: Error) => void) {
  const fields = value.trim().split(/\s+/)
  done(fields.length === 5 ? undefined : new Error('Cron 表达式需要五个字段'))
}
</script>

<template>
  <SectionCard title="基本信息与运行策略">
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
        <el-select :model-value="schedule" @update:model-value="changeSchedule">
          <el-option value="manual" label="仅手动运行" />
          <el-option value="cron" label="Cron 定时运行" />
          <el-option v-if="schedule === 'legacy'" value="legacy" label="旧版定时间隔" disabled />
        </el-select>
      </el-form-item>
      <el-form-item
        v-if="schedule === 'cron'"
        label="Cron 表达式（分 时 日 月 周）"
        prop="cron"
        :rules="[{ required: true, message: '请输入 Cron 表达式' }, { validator: validateCron }]"
      >
        <el-input
          :model-value="draft.cron"
          placeholder="0 9 * * *"
          @update:model-value="emit('update', { cron: $event })"
        />
      </el-form-item>
      <el-form-item v-if="schedule === 'cron'" label="计划时区（IANA）">
        <el-select
          :model-value="draft.cron_timezone"
          filterable
          allow-create
          default-first-option
          @update:model-value="emit('update', { cron_timezone: $event })"
        >
          <el-option v-for="zone in timezones" :key="zone" :value="zone" :label="zone" />
        </el-select>
      </el-form-item>
    </div>
    <el-alert
      v-if="schedule === 'legacy'"
      :title="`当前保留旧版每 ${draft.interval_seconds} 秒运行；选择 Cron 或仅手动运行后替换此计划。`"
      type="warning"
      :closable="false"
    />
  </SectionCard>
</template>
