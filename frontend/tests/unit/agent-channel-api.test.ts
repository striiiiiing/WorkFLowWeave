import { afterEach, expect, it, vi } from 'vitest'
import { agentsApi } from '@/api/agents'

afterEach(() => vi.unstubAllGlobals())

it('routes every conversation action through the Web channel and unwraps its result', async () => {
  const result = { session_id: 'session', turn_id: 'turn' }
  const fetch = vi.fn(
    async (_input: RequestInfo | URL, _options?: RequestInit) =>
      new Response(JSON.stringify({ kind: 'turn', result })),
  )
  vi.stubGlobal('fetch', fetch)

  const cases = [
    [() => agentsApi.create({ model: 'model' }), { action: 'new', model: 'model' }],
    [
      () => agentsApi.create({ workflow_id: 'workflow' }),
      { action: 'workflow', workflow_id: 'workflow' },
    ],
    [
      () => agentsApi.send('session', 'message-id', '/literal text'),
      { action: 'message', session: 'session', request_id: 'message-id', text: '/literal text' },
    ],
    [
      () => agentsApi.append('session', 'append-id', 'more'),
      { action: 'append', session: 'session', request_id: 'append-id', text: 'more' },
    ],
    [
      () => agentsApi.fork('session', { message_id: 'message' }),
      { action: 'fork', session: 'session', message_id: 'message' },
    ],
    [() => agentsApi.cancel('session'), { action: 'stop', session: 'session' }],
    [() => agentsApi.compact('session'), { action: 'compact', session: 'session' }],
  ] as const

  for (const [call, payload] of cases) {
    expect(await call()).toEqual(result)
    expect(fetch).toHaveBeenLastCalledWith(
      '/api/channels/web/commands',
      expect.objectContaining({
        method: 'POST',
        body: expect.any(String),
      }),
    )
    const options = fetch.mock.lastCall![1] as RequestInit
    expect(JSON.parse(options.body as string)).toMatchObject({ channel: 'web', ...payload })
  }

  await agentsApi.command('session', '/stop', 'stop-id')
  const options = fetch.mock.lastCall![1] as RequestInit
  expect(JSON.parse(options.body as string)).toEqual({
    channel: 'web',
    session: 'session',
    text: '/stop',
    request_id: 'stop-id',
  })
})
