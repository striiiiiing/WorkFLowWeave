import { effectScope } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/shared/api/errors'
import type { AgentsApi } from '@/modules/agents/api/agentsApi'
import { useAgentCommands } from '@/modules/agents/composables/useAgentCommands'
import { useAgentFiles } from '@/modules/agents/composables/useAgentFiles'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

const turn = (id: string) => ({
  kind: 'turn' as const,
  priority: 'conversation',
  result: { session_id: id, turn_id: 't', deduplicated: false },
})

describe('Agent commands', () => {
  it('isolates A -> B -> A drafts and late receipts', async () => {
    const pending = deferred<ReturnType<typeof turn>>()
    const command = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue(turn('B'))
    const commands = useAgentCommands({ command, cancel: vi.fn() } as unknown as AgentsApi)
    commands.select('A')
    commands.draft.value = 'A message'
    const sendA = commands.send(false)
    commands.select('B')
    commands.draft.value = 'B message'
    pending.resolve(turn('A'))
    await sendA
    expect(commands.draft.value).toBe('B message')
    expect(commands.stateFor('A').draft).toBe('')
    commands.select('A')
    expect(commands.draft.value).toBe('')
    commands.select('B')
    expect(await commands.send(false)).toEqual(turn('B'))
  })

  it('retains an unknown request ID for explicit retry and creates a new ID after editing', async () => {
    const command = vi.fn().mockRejectedValueOnce(new TypeError('lost')).mockResolvedValue(turn('A'))
    const commands = useAgentCommands({ command, cancel: vi.fn() } as unknown as AgentsApi)
    commands.select('A')
    commands.draft.value = 'first'
    await commands.send(false)
    expect(commands.current.value.uncertain).toBe(true)
    await commands.send(false)
    expect(command.mock.calls[0][2]).toBe(command.mock.calls[1][2])
    commands.draft.value = 'second'
    await commands.send(false)
    expect(command.mock.calls[2][2]).not.toBe(command.mock.calls[0][2])
  })

  it('leaves stop available while send awaits its receipt', async () => {
    const pending = deferred<ReturnType<typeof turn>>()
    const cancel = vi.fn().mockResolvedValue({ session_id: 'A', status: 'running' })
    const commands = useAgentCommands({ command: vi.fn(() => pending.promise), cancel } as unknown as AgentsApi)
    commands.select('A')
    commands.draft.value = 'message'
    const sending = commands.send(false)
    expect(commands.current.value.pending).toBe(true)
    await commands.stop()
    expect(cancel).toHaveBeenCalledWith('A')
    pending.resolve(turn('A'))
    await sending
  })

  it('does not retry uncertain workflow creation with a duplicate side effect', async () => {
    const command = vi.fn().mockRejectedValue(new TypeError('lost'))
    const commands = useAgentCommands({ command, cancel: vi.fn() } as unknown as AgentsApi)
    commands.select('A')
    commands.draft.value = '/workflow run-1'
    await commands.send(false)
    expect(commands.current.value.retrySafe).toBe(false)
    await commands.send(false)
    expect(command).toHaveBeenCalledTimes(1)
  })
})

describe('Agent files', () => {
  it('preserves the local draft on ETag conflict and resumes with the remote hash', async () => {
    const readFile = vi.fn().mockResolvedValue({ path: 'Memory/a.md', kind: 'file', content: 'remote', hash: 'v1', readonly: false, offset: 0, next_offset: null })
    const writeFile = vi.fn().mockRejectedValueOnce(new ApiError(409, { code: 'conflict', message: 'changed', details: {} })).mockResolvedValue({ hash: 'v3' })
    const scope = effectScope()
    const files = scope.run(() => useAgentFiles({ readFile, writeFile } as unknown as AgentsApi))!
    files.reset('A', 'Memory/a.md')
    await files.read()
    files.draft.value = 'local edit'
    await files.save()
    expect(files.conflict.value).toBe(true)
    expect(files.draft.value).toBe('local edit')
    await files.readRemote()
    readFile.mockResolvedValue({ path: 'Memory/a.md', kind: 'file', content: 'new remote', hash: 'v2', readonly: false, offset: 0, next_offset: null })
    await files.readRemote()
    files.mergeRemote()
    await files.save()
    expect(writeFile).toHaveBeenLastCalledWith('A', 'Memory/a.md', 'local edit', 'v2')
    scope.stop()
  })
})
