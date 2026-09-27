import { computed, ref, watch, type Ref } from 'vue'
import { errorMessage } from '@/shared/api/errors'
import { useWorkflowsApi } from '../api/dependencies'
import type { CronPreview } from '../api/workflowsApi'
import type { WorkflowSchedule } from '../model/types'

type CronSchedule = Extract<WorkflowSchedule, { type: 'cron' }>

export function useCronPreview(cron: Readonly<Ref<CronSchedule | null>>) {
  const api = useWorkflowsApi()
  const preview = ref<CronPreview | null>(null)
  const pending = ref(false)
  const error = ref('')
  const nextRun = computed(() =>
    preview.value
      ? new Intl.DateTimeFormat('zh-CN', {
          timeZone: preview.value.timezone,
          dateStyle: 'medium',
          timeStyle: 'medium',
        }).format(new Date(preview.value.next_run_at))
      : '',
  )

  watch(
    () => [cron.value?.expression, cron.value?.timezone] as const,
    ([expression, timezone], _previous, onCleanup) => {
      preview.value = null
      error.value = ''
      pending.value = false
      if (!expression?.trim()) return
      if (expression.trim().split(/\s+/).length !== 5) {
        error.value = 'Cron 表达式需要五个字段'
        return
      }
      const controller = new AbortController()
      let active = true
      pending.value = true
      const timer = setTimeout(async () => {
        try {
          const result = await api.previewCron(expression, timezone ?? null, controller.signal)
          if (active) preview.value = result
        } catch (cause) {
          if (active) error.value = `预览失败：${errorMessage(cause)}`
        } finally {
          if (active) pending.value = false
        }
      }, 300)
      onCleanup(() => {
        active = false
        clearTimeout(timer)
        controller.abort()
      })
    },
    { immediate: true },
  )

  return { preview, pending, error, nextRun }
}
