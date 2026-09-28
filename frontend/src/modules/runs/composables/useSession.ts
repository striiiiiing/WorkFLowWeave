import { onScopeDispose, ref, shallowReadonly, shallowRef, watch, type Ref } from 'vue'
import { useErrorFormatter } from '@/shared/async/errorFormatter'
import { useRunsApi } from '../api/dependencies'
import type { RunsApi } from '../api/runsApi'
import { isTerminalStatus } from '../model/progress'
import type { SessionRecord } from '../model/types'

export type RunConnectionState = 'connecting' | 'connected' | 'reconnecting' | 'closed'

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
  let disposed = false
  let unsubscribe: (() => void) | undefined
  let controller: AbortController | undefined

  function closeConnection() {
    generation++
    unsubscribe?.()
    unsubscribe = undefined
  }

  function release() {
    controller?.abort()
    controller = undefined
    closeConnection()
    pending.value = false
  }

  function accept(snapshot: SessionRecord, sessionId: string) {
    if (snapshot.session_id !== sessionId) throw new Error('Workflow 快照会话不匹配')
    const current = data.value
    if (current && snapshot.version <= current.version) return
    data.value = snapshot
    snapshotVersion.value = snapshot.version
    readAt.value = Date.now()
  }

  async function query(sessionId: string, owner: number) {
    controller?.abort()
    const request = new AbortController()
    controller = request
    pending.value = true
    error.value = ''
    try {
      const snapshot = await api.get(sessionId, request.signal)
      if (owner !== generation || request.signal.aborted || controller !== request) return
      accept(snapshot, sessionId)
    } catch (cause) {
      if (owner === generation && !request.signal.aborted && controller === request)
        error.value = formatError(cause)
    } finally {
      if (controller === request) {
        controller = undefined
        pending.value = false
      }
    }
  }

  function connect() {
    if (disposed) return
    closeConnection()
    const owner = generation
    const sessionId = id.value
    connection.value = 'connecting'
    connectionError.value = ''
    const subscribe = api.subscribe
    if (!subscribe || subscribe.available === false) {
      connection.value = 'reconnecting'
      connectionError.value = '当前浏览器不支持进度订阅，请手动同步'
      void query(sessionId, owner)
      return
    }
    pending.value = !data.value
    unsubscribe = subscribe(sessionId, {
      snapshot: (snapshot) => {
        if (owner !== generation || disposed) return
        try {
          accept(snapshot, sessionId)
        } catch (cause) {
          closeConnection()
          connection.value = 'closed'
          connectionError.value = formatError(cause)
          pending.value = false
          return
        }
        pending.value = false
        error.value = ''
        connectionError.value = ''
        if (isTerminalStatus(snapshot.status) && data.value?.version === snapshot.version) {
          closeConnection()
          connection.value = 'closed'
        } else connection.value = 'connected'
      },
      state: (state) => {
        if (owner !== generation || disposed) return
        connection.value = state
        connectionError.value = state === 'reconnecting'
          ? '进度连接中断，正在重新连接；当前显示最后已知结果'
          : ''
        if (state === 'reconnecting') pending.value = false
      },
      error: (cause) => {
        if (owner !== generation || disposed) return
        closeConnection()
        connection.value = 'closed'
        connectionError.value = formatError(cause)
        pending.value = false
      },
    })
  }

  async function refresh() {
    if (disposed) return
    if (api.subscribe && api.subscribe.available !== false) connect()
    await query(id.value, generation)
  }

  watch(id, () => {
    release()
    data.value = undefined
    snapshotVersion.value = undefined
    error.value = ''
    readAt.value = undefined
    connect()
  }, { immediate: true })
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
