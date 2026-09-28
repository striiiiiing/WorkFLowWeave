import { onScopeDispose, ref, shallowReadonly, shallowRef, watch, type Ref } from 'vue'
import { useErrorFormatter } from '@/shared/async/errorFormatter'
import { useRunsApi } from '../api/dependencies'
import type { RunsApi } from '../api/runsApi'
import {
  applyProgress,
  isTerminalStatus,
  mergeSessionSnapshot,
  progressIdentity,
} from '../model/progress'
import type { SessionRecord, WorkflowProgress } from '../model/types'

// Matches the backend's bounded observer queue; overflow requires an explicit resync.
export const SYNC_BUFFER_CAPACITY = 64
export type RunConnectionState = 'connecting' | 'syncing' | 'connected' | 'reconnecting' | 'closed'

type SessionApi = Pick<RunsApi, 'get'> & Partial<Pick<RunsApi, 'subscribe'>>
export function useSession(id: Ref<string>, api: SessionApi = useRunsApi()) {
  const data = shallowRef<SessionRecord>()
  const pending = ref(false)
  const error = ref('')
  const readAt = ref<number>()
  const snapshotVersion = ref<number>()
  const connection = ref<RunConnectionState>('connecting')
  const connectionError = ref('')
  const formatError = useErrorFormatter()
  let generation = 0
  let connectionGeneration = 0
  let queryGeneration = 0
  let disposed = false
  let ready = false
  let unsubscribe: (() => void) | undefined
  let controller: AbortController | undefined
  let buffered = new Map<string, WorkflowProgress>()

  const subscribe = api.subscribe
  const subscriptionUnavailable = !subscribe || subscribe.available === false

  function closeConnection() {
    connectionGeneration++
    unsubscribe?.()
    unsubscribe = undefined
    ready = false
  }

  function release() {
    generation++
    queryGeneration++
    controller?.abort()
    controller = undefined
    closeConnection()
    buffered.clear()
    pending.value = false
  }

  function buffer(event: WorkflowProgress) {
    const key = `${event.execution_epoch}:${progressIdentity(event)}`
    const previous = buffered.get(key)
    if (previous && (previous.version ?? -1) >= (event.version ?? -1)) return true
    if (!previous && buffered.size >= SYNC_BUFFER_CAPACITY) {
      controller?.abort()
      queryGeneration++
      closeConnection()
      pending.value = false
      connection.value = 'reconnecting'
      connectionError.value = '同步期间进度过多，连接已中断，请重新同步'
      buffered.clear()
      return false
    }
    buffered.set(key, event)
    return true
  }

  async function synchronize() {
    if (disposed || !ready) return
    controller?.abort()
    const request = new AbortController()
    controller = request
    const owner = generation
    const queryOwner = ++queryGeneration
    const sessionId = id.value
    pending.value = true
    connection.value = 'syncing'
    error.value = ''
    try {
      const snapshot = await api.get(sessionId, request.signal)
      if (request.signal.aborted || owner !== generation || queryOwner !== queryGeneration) return
      if (snapshot.session_id !== sessionId) throw new Error('Workflow 查询会话不匹配')
      const current = data.value
      const accepted =
        !current ||
        snapshot.version >= current.version ||
        snapshot.execution_epoch === current.execution_epoch
      let next = accepted ? mergeSessionSnapshot(current, snapshot) : current!
      const updates = [...buffered.values()].sort((a, b) => (a.version ?? -1) - (b.version ?? -1))
      buffered.clear()
      for (const event of updates) {
        if (event.execution_epoch === next.execution_epoch) next = applyProgress(next, event)
        else if ((event.version ?? -1) > next.version) buffer(event)
      }
      data.value = next
      snapshotVersion.value = snapshot.version
      readAt.value = Date.now()
      controller = undefined
      pending.value = false
      if (buffered.size) {
        // A new epoch arrived after the snapshot was read; confirm it through the same query.
        await synchronize()
        return
      }
      if (isTerminalStatus(next.status) && !isTerminalStatus(snapshot.status)) {
        await synchronize()
        return
      }
      connectionError.value = subscriptionUnavailable ? '当前浏览器不支持进度订阅，请手动同步' : ''
      if (isTerminalStatus(next.status)) {
        closeConnection()
        connection.value = 'closed'
      } else {
        connection.value = ready && !subscriptionUnavailable ? 'connected' : 'reconnecting'
      }
    } catch (cause) {
      if (!request.signal.aborted && owner === generation && queryOwner === queryGeneration) {
        error.value = formatError(cause)
        pending.value = false
        controller = undefined
        connection.value = 'reconnecting'
        connectionError.value = '进度尚未同步，请重新同步'
      }
    }
  }

  function connect() {
    if (disposed) return
    closeConnection()
    const owner = generation
    const connectionOwner = connectionGeneration
    const sessionId = id.value
    connection.value = 'connecting'
    connectionError.value = ''
    if (!subscribe || subscriptionUnavailable) {
      // A snapshot remains readable when subscriptions are unavailable; resync is explicit.
      ready = true
      void synchronize()
      return
    }
    unsubscribe = subscribe(sessionId, {
      ready: () => {
        if (owner !== generation || connectionOwner !== connectionGeneration || disposed) return
        ready = true
        void synchronize()
      },
      progress: (event) => {
        if (owner !== generation || connectionOwner !== connectionGeneration || disposed) return
        if (event.session_id !== sessionId) {
          closeConnection()
          connection.value = 'reconnecting'
          connectionError.value = 'Workflow 进度会话不匹配，请重新同步'
          return
        }
        const current = data.value
        if (
          pending.value ||
          !current ||
          !ready ||
          event.execution_epoch !== current.execution_epoch
        ) {
          if (
            current &&
            event.execution_epoch !== current.execution_epoch &&
            (event.version ?? -1) <= current.version
          )
            return
          if (buffer(event) && !pending.value && ready) void synchronize()
          return
        }
        data.value = applyProgress(current, event)
        if (event.event === 'lifecycle' && isTerminalStatus(event.status)) void synchronize()
      },
      disconnected: (message) => {
        if (owner !== generation || connectionOwner !== connectionGeneration || disposed) return
        ready = false
        controller?.abort()
        queryGeneration++
        pending.value = false
        connection.value = 'reconnecting'
        connectionError.value = message
      },
    })
  }

  async function refresh() {
    if (disposed) return
    if (ready) await synchronize()
    else {
      release()
      connect()
    }
  }

  watch(
    id,
    () => {
      release()
      data.value = undefined
      snapshotVersion.value = undefined
      error.value = ''
      readAt.value = undefined
      connect()
    },
    { immediate: true },
  )
  onScopeDispose(() => {
    disposed = true
    release()
  })
  return {
    data: shallowReadonly(data),
    pending: shallowReadonly(pending),
    error: shallowReadonly(error),
    readAt: shallowReadonly(readAt),
    snapshotVersion: shallowReadonly(snapshotVersion),
    connection: shallowReadonly(connection),
    connectionError: shallowReadonly(connectionError),
    refresh,
  }
}
