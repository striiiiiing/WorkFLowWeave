import { effectScope, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createResourcesApi } from '@/modules/resources/api/resourcesApi'
import { useChannelEditor } from '@/modules/resources/composables/useChannelEditor'
import { createResource, type ChannelConfig } from '@/modules/resources/model/public'
import type { SchemaCapability } from '@/shared/schema/types'

const flushPromises = () => new Promise<void>((resolve) => setTimeout(resolve, 0))

const waiting = {
  channel_id: 'qq-instance',
  state: 'waiting_message' as const,
  message: '等待首条私聊消息',
  error: null,
  target_options: {},
}
const connected = {
  ...waiting,
  state: 'connected' as const,
  message: '成功连接',
  target_options: { target_kind: 'c2c', target_id: 'platform-open-id' },
}

function capability(name = 'qq'): SchemaCapability {
  return {
    name,
    description: '',
    capabilities: ['notification', 'conversation'],
    options_schema: {
      type: 'object',
      properties: {
        app_id: { type: 'string' },
        client_secret: { type: 'string', 'x-workflowweave-credential': true },
        target_kind: { type: 'string', 'x-workflowweave-workflow': true },
        target_id: { type: 'string', 'x-workflowweave-workflow': true },
      },
      'x-workflowweave-first-message': true,
    },
  }
}

function resource(overrides: Partial<ChannelConfig> = {}): ChannelConfig {
  return {
    ...(createResource('channels') as ChannelConfig),
    id: 'qq-instance',
    channel: 'qq',
    enabled: true,
    options: { app_id: 'app' },
    ...overrides,
  }
}

function editorApi(initial?: ChannelConfig) {
  const saved = initial ?? resource()
  const api = {
    create: vi.fn(async (_kind: string, value: ChannelConfig) => value),
    replace: vi.fn(async (_kind: string, _id: string, value: ChannelConfig) => value),
    protectCredential: vi.fn(async (value: string) => ({
      kind: 'encrypted' as const,
      format_version: 1,
      key_id: 'test-key',
      ciphertext: value,
    })),
    startChannelConnection: vi.fn(async (id: string) => ({ ...waiting, channel_id: id })),
    channelConnection: vi.fn(async (id: string) => ({ ...connected, channel_id: id })),
    cancelChannelConnection: vi.fn(async (id: string) => ({
      ...waiting,
      channel_id: id,
      state: 'cancelled' as const,
      message: '连接已取消',
    })),
    get: vi.fn(async (_kind: string, id: string) => ({
      ...saved,
      id,
      options: { ...saved.options, ...connected.target_options },
    })),
  }
  return api
}

async function flushMicrotasks() {
  for (let index = 0; index < 12; index += 1) await Promise.resolve()
}

afterEach(() => vi.useRealTimers())

describe('channel first-message connection API', () => {
  it('uses the channel connection resource routes for start, status, and cancellation', async () => {
    const request = vi.fn().mockResolvedValue(waiting)
    const api = createResourcesApi({ request })
    await api.startChannelConnection('instance / one')
    await api.channelConnection('instance / one')
    await api.cancelChannelConnection('instance / one')
    expect(request.mock.calls.map(([call]) => [call.method, call.url])).toEqual([
      ['POST', '/channels/instance%20%2F%20one/connection'],
      [undefined, '/channels/instance%20%2F%20one/connection'],
      ['DELETE', '/channels/instance%20%2F%20one/connection'],
    ])
  })
})

describe('channel first-message editor flow', () => {
  it('polls each second, reloads the persisted target, and exposes success for completion', async () => {
    const api = editorApi()
    api.channelConnection
      .mockImplementationOnce(async (id) => ({ ...waiting, channel_id: id }))
      .mockImplementationOnce(async (id) => ({ ...connected, channel_id: id }))
    const scope = effectScope()
    const state = scope.run(() => useChannelEditor({ capabilities: [capability()] }, api))!
    state.updateChannel('qq')
    await nextTick()
    state.updateOptions({ app_id: 'app' })
    const saved = await state.submit(async () => true)
    expect(saved.status).toBe('success')
    if (saved.status !== 'success') throw new Error('channel save failed')
    const connecting = state.startConnection(saved.value.id)
    await flushMicrotasks()
    expect(api.startChannelConnection).toHaveBeenCalledWith(saved.value.id)
    expect(state.connection.value?.state).toBe('waiting_message')
    await new Promise((resolve) => setTimeout(resolve, 1050))
    await connecting
    expect(api.get).toHaveBeenCalledWith('channels', saved.value.id)
    expect(state.draft.value.options).toMatchObject({
      target_kind: 'c2c',
      target_id: 'platform-open-id',
    })
    expect(state.connection.value?.state).toBe('connected')
    expect(state.connectionReady.value).toBe(true)
    expect(state.finishRequired.value).toBe(true)
    expect(await state.finishConnection()).toMatchObject({ id: saved.value.id })
    scope.stop()
  }, 10_000)

  it('uses the persisted resource returned by GET as the target source of truth', async () => {
    const api = editorApi()
    api.channelConnection
      .mockImplementationOnce(async (id) => ({ ...waiting, channel_id: id }))
      .mockImplementationOnce(async (id) => ({ ...connected, channel_id: id }))
    api.get.mockResolvedValue({
      ...resource(),
      options: { app_id: 'app', target_kind: 'persisted-kind', target_id: 'persisted-id' },
    })
    const scope = effectScope()
    const state = scope.run(() => useChannelEditor({ capabilities: [capability()] }, api))!
    state.updateChannel('qq')
    await nextTick()
    state.updateOptions({ app_id: 'app' })
    const saved = await state.submit(async () => true)
    expect(saved.status).toBe('success')
    if (saved.status !== 'success') throw new Error('channel save failed')
    await state.startConnection(saved.value.id)
    expect(state.draft.value.options).toMatchObject({
      target_kind: 'persisted-kind',
      target_id: 'persisted-id',
    })
    expect(state.draft.value.options).not.toMatchObject({ target_id: 'platform-open-id' })
    scope.stop()
  }, 10_000)

  it('retries a failed first connection with replace on the saved resource ID', async () => {
    const api = editorApi()
    api.startChannelConnection
      .mockImplementationOnce(async (id) => ({
        ...waiting,
        channel_id: id,
        state: 'failed',
        message: '认证失败',
        error: { code: 'auth_failed', message: '认证失败', details: {} },
      }))
      .mockImplementationOnce(async (id) => ({ ...connected, channel_id: id }))
    const scope = effectScope()
    const state = scope.run(() => useChannelEditor({ capabilities: [capability()] }, api))!
    state.updateChannel('qq')
    await nextTick()
    state.updateOptions({ app_id: 'app' })
    const first = await state.submit(async () => true)
    if (first.status !== 'success') throw new Error('initial channel save failed')
    await state.startConnection(first.value.id)
    const retry = await state.submit(async () => true)
    if (retry.status !== 'success') throw new Error('channel retry save failed')
    await state.startConnection(retry.value.id, true)
    expect(api.create).toHaveBeenCalledTimes(1)
    expect(api.replace).toHaveBeenCalledTimes(1)
    expect(api.replace).toHaveBeenCalledWith('channels', first.value.id, expect.any(Object))
    expect(state.connection.value?.state).toBe('connected')
    scope.stop()
  })

  it('cancels a live wait and ignores subsequent status results', async () => {
    const api = editorApi()
    const scope = effectScope()
    const state = scope.run(() =>
      useChannelEditor(
        {
          initial: resource(),
          capabilities: [capability()],
        },
        api,
      ),
    )!
    await flushMicrotasks()
    api.channelConnection.mockResolvedValue({ ...waiting, channel_id: 'qq-instance' })
    const connecting = state.startConnection('qq-instance')
    await flushMicrotasks()
    await state.cancelConnection('已取消首次连接。')
    await connecting
    expect(api.cancelChannelConnection).toHaveBeenCalledWith('qq-instance')
    expect(state.connection.value?.state).toBe('cancelled')
    expect(api.channelConnection).toHaveBeenCalledTimes(1)
    scope.stop()
  })
})
