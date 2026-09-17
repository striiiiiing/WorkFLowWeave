import { defineStore } from 'pinia'
import { ref } from 'vue'
import { runsApi, type ListSessionsParams } from '@/api/runs'
import type { SessionRecord, PhaseContent, StageName, ID } from '@/types'

export const useRunStore = defineStore('run', () => {
  const sessions = ref<SessionRecord[]>([])
  const activeSession = ref<SessionRecord | null>(null)
  const phaseContents = ref<Record<string, PhaseContent>>({})
  const loading = ref(false)
  const error = ref<string | null>(null)

  let pollTimer: ReturnType<typeof setInterval> | null = null

  async function fetchSessions(params: ListSessionsParams = {}) {
    loading.value = true
    error.value = null
    try {
      sessions.value = await runsApi.listSessions(params)
    } catch (e: any) {
      error.value = e.message || '获取运行记录失败'
    } finally {
      loading.value = false
    }
  }

  async function fetchSessionDetail(sessionId: ID, version?: number) {
    loading.value = true
    try {
      const record = await runsApi.getSession(sessionId, version)
      activeSession.value = record
      return record
    } finally {
      loading.value = false
    }
  }

  async function fetchPhaseContent(sessionId: ID, stage: StageName, version: number) {
    const key = `${sessionId}_${stage}_${version}`
    if (phaseContents.value[key]) {
      return phaseContents.value[key]
    }

    const content = await runsApi.getPhaseContent(sessionId, stage, version)
    phaseContents.value[key] = content
    return content
  }

  async function triggerWorkflow(workflowId: ID): Promise<ID> {
    const res = await runsApi.triggerWorkflow(workflowId)
    return res.session_id
  }

  async function cancelRun(sessionId: ID) {
    await runsApi.cancelRun(sessionId)
    if (activeSession.value && activeSession.value.session_id === sessionId) {
      activeSession.value.status = 'cancelled'
    }
    const item = sessions.value.find((s) => s.session_id === sessionId)
    if (item) item.status = 'cancelled'
  }

  async function recoverRun(sessionId: ID) {
    const res = await runsApi.recoverRun(sessionId)
    return res.session_id
  }

  // [Design Decision DEC-MOTION-01] 活动 Session 自动轮询机制（默认间隔 2000ms）
  function startPolling(sessionId: ID, intervalMs = 2000) {
    stopPolling()
    pollTimer = setInterval(async () => {
      try {
        const detail = await runsApi.getSession(sessionId)
        activeSession.value = detail
        // 终态停止轮询
        if (
          detail.status === 'completed' ||
          detail.status === 'partial' ||
          detail.status === 'failed' ||
          detail.status === 'cancelled'
        ) {
          stopPolling()
        }
      } catch {
        stopPolling()
      }
    }, intervalMs)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  return {
    sessions,
    activeSession,
    phaseContents,
    loading,
    error,
    fetchSessions,
    fetchSessionDetail,
    fetchPhaseContent,
    triggerWorkflow,
    cancelRun,
    recoverRun,
    startPolling,
    stopPolling,
  }
})
