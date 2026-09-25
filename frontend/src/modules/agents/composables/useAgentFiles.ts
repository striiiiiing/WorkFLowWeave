import { computed, ref } from 'vue'
import { ApiError } from '@/shared/api/errors'
import { useErrorFormatter } from '@/shared/async/errorFormatter'
import type { AgentsApi } from '../api/agentsApi'
import type { AgentFile } from '../model/types'

type FileApi = Pick<AgentsApi, 'readFile' | 'writeFile'>

export function useAgentFiles(api: FileApi) {
  const formatError = useErrorFormatter()
  const sessionId = ref('')
  const path = ref('AGENTS.md')
  const page = ref<AgentFile>()
  const draft = ref('')
  const version = ref('')
  const complete = ref(false)
  const conflict = ref(false)
  const remote = ref<AgentFile>()
  const notice = ref('')
  const error = ref('')
  const pending = ref(false)
  const editable = computed(
    () => page.value?.kind === 'file' && !page.value.readonly && complete.value,
  )
  let generation = 0

  function reset(id: string, initialPath: string) {
    generation++
    sessionId.value = id
    path.value = initialPath
    page.value = undefined
    draft.value = ''
    version.value = ''
    complete.value = false
    conflict.value = false
    remote.value = undefined
    notice.value = ''
    error.value = ''
  }

  async function read(offset = 0) {
    const id = sessionId.value
    const requestedPath = path.value
    const current = ++generation
    pending.value = true
    error.value = ''
    try {
      const result = await api.readFile(id, requestedPath, offset)
      if (current !== generation) return
      page.value = result
      draft.value = result.content ?? ''
      version.value = result.hash ?? ''
      complete.value = offset === 0 && result.next_offset === null
      conflict.value = false
      remote.value = undefined
      notice.value = ''
    } catch (cause) {
      if (current === generation) error.value = formatError(cause)
    } finally {
      if (current === generation) pending.value = false
    }
  }

  async function wholeFile(id: string, filePath: string): Promise<AgentFile> {
    let result = await api.readFile(id, filePath)
    const first = result
    let content = result.content ?? ''
    while (result.next_offset !== null) {
      result = await api.readFile(id, filePath, result.next_offset)
      if (result.hash !== first.hash) throw new Error('读取期间文件发生变化，请重新载入')
      content += result.content ?? ''
    }
    return { ...first, content, next_offset: null }
  }

  async function loadFull() {
    const current = ++generation
    pending.value = true
    error.value = ''
    try {
      const result = await wholeFile(sessionId.value, page.value?.path ?? path.value)
      if (current !== generation) return
      page.value = result
      draft.value = result.content ?? ''
      version.value = result.hash ?? ''
      complete.value = true
    } catch (cause) {
      if (current === generation) error.value = formatError(cause)
    } finally {
      if (current === generation) pending.value = false
    }
  }

  async function save() {
    if (!editable.value || !page.value || conflict.value || pending.value) return
    const id = sessionId.value
    const filePath = page.value.path
    const content = draft.value
    const hash = version.value
    const current = generation
    pending.value = true
    error.value = ''
    try {
      const result = await api.writeFile(id, filePath, content, hash)
      if (current !== generation) return
      version.value = result.hash
      conflict.value = false
      remote.value = undefined
      notice.value = '文件已保存，下一轮生效'
    } catch (cause) {
      if (current === generation) {
        if (cause instanceof ApiError && cause.status === 409) conflict.value = true
        error.value = formatError(cause)
      }
    } finally {
      if (current === generation) pending.value = false
    }
  }

  async function readRemote() {
    const current = generation
    pending.value = true
    error.value = ''
    try {
      const result = await wholeFile(sessionId.value, page.value?.path ?? path.value)
      if (current === generation) remote.value = result
    } catch (cause) {
      if (current === generation) error.value = formatError(cause)
    } finally {
      if (current === generation) pending.value = false
    }
  }

  function mergeRemote() {
    if (!remote.value?.hash) return
    version.value = remote.value.hash
    conflict.value = false
    error.value = ''
    notice.value = '已采用最新版本号；草稿已保留，请合并后保存'
  }

  function createFile() {
    generation++
    page.value = { path: path.value, kind: 'file', readonly: false, offset: 0, next_offset: null }
    draft.value = ''
    version.value = '*'
    complete.value = true
    conflict.value = false
    remote.value = undefined
    error.value = ''
    notice.value = '新文件使用不存在条件创建；已有文件不会被覆盖'
  }

  function openPath(value: string) {
    path.value = value
    void read()
  }

  function openEntry(name: string) {
    openPath(`${path.value === '.' ? '' : path.value + '/'}${name}`)
  }

  return {
    path,
    page,
    draft,
    version,
    complete,
    conflict,
    remote,
    notice,
    error,
    pending,
    editable,
    reset,
    read,
    loadFull,
    save,
    readRemote,
    mergeRemote,
    createFile,
    openPath,
    openEntry,
  }
}
