import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useResourcesApi } from '../api/dependencies'
import type { ChannelLoginStatus, ResourcesApi } from '../api/resourcesApi'
import type { JsonObject } from '@/shared/types'

const POLL_INTERVAL = 1000
type LoginApi = Pick<ResourcesApi,
  'startChannelLogin' | 'channelLoginStatus' | 'verifyChannelLogin' | 'cancelChannelLogin'>

export function useWechatLogin(
  options: () => JsonObject,
  update: (value: JsonObject) => void,
  api: LoginApi = useResourcesApi(),
) {
  const status = shallowRef<ChannelLoginStatus>()
  const error = ref('')
  const busy = ref(false)
  const code = ref('')
  let generation = 0
  let alive = true
  let timer: ReturnType<typeof setTimeout> | undefined
  let sessionId: string | undefined
  const current = (version: number) => alive && version === generation
  const loginOptions = computed(() => ({ command: options().command ?? 'node',
    state_dir: options().state_dir ?? null }))
  const report = (cause: unknown) => {
    if (alive) error.value = cause instanceof Error ? cause.message : String(cause)
  }

  async function release() {
    clearTimeout(timer)
    const id = sessionId
    if (id) {
      await api.cancelChannelLogin(id)
      if (sessionId === id) sessionId = undefined
    }
  }

  async function accept(value: ChannelLoginStatus, version: number) {
    if (!current(version)) return
    status.value = value
    if (value.state === 'connected') {
      if (!value.account_id) throw new Error('微信登录未返回账号 ID')
      update({ ...options(), ...value.options, account_id: value.account_id })
      await release()
      return
    }
    if (value.state === 'failed') {
      error.value = value.message
      await release()
      return
    }
    timer = setTimeout(() => void poll(version), POLL_INTERVAL)
  }

  async function poll(version: number) {
    if (!current(version) || !sessionId) return
    try {
      await accept(await api.channelLoginStatus(sessionId), version)
    } catch (cause) {
      if (current(version)) report(cause)
    }
  }

  async function cancel() {
    generation += 1
    busy.value = false
    status.value = undefined
    code.value = ''
    try { await release() } catch (cause) { report(cause) }
  }

  async function start() {
    const version = ++generation
    error.value = ''
    busy.value = true
    status.value = undefined
    code.value = ''
    try {
      await release()
      if (!current(version)) return
      const value = await api.startChannelLogin('wechat_openclaw', loginOptions.value)
      if (!current(version)) {
        await api.cancelChannelLogin(value.session_id)
        return
      }
      sessionId = value.session_id
      await accept(value, version)
    } catch (cause) {
      if (current(version)) report(cause)
    } finally {
      if (current(version)) busy.value = false
    }
  }

  async function verify() {
    if (!/^[0-9]{1,16}$/.test(code.value)) {
      error.value = '请输入 1 至 16 位数字'
      return
    }
    if (!sessionId || status.value?.state !== 'verify_required') return
    const version = generation
    clearTimeout(timer)
    busy.value = true
    error.value = ''
    try {
      await accept(await api.verifyChannelLogin(sessionId, code.value), version)
      if (current(version)) code.value = ''
    } catch (cause) {
      if (current(version)) {
        report(cause)
        timer = setTimeout(() => void poll(version), POLL_INTERVAL)
      }
    } finally {
      if (current(version)) busy.value = false
    }
  }

  watch(loginOptions, (next, previous) => {
    if (next.command !== previous.command || next.state_dir !== previous.state_dir) {
      // Connected callbacks normalize the path; don't cancel that successful update.
      if (status.value?.state !== 'connected') void cancel()
    }
  })
  onBeforeUnmount(() => {
    alive = false
    generation += 1
    void release().catch((cause) => console.error('微信登录会话取消失败', cause))
  })
  return { status, error, busy, code, start, cancel, verify }
}
