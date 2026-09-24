import { expect, it } from 'vitest'
import { createHttpHarness } from '../helpers/httpHarness'

it('routes every conversation action through the Web channel and unwraps its result', async () => {
  const result = { session_id: 'session', turn_id: 'turn' }
  const { agentsApi, respond, lastRequest } = createHttpHarness()
  const adapter = respond({ kind: 'turn', result })

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
    expect(adapter).toHaveBeenLastCalledWith(
      expect.objectContaining({
        url: '/channels/web/commands',
        method: 'post',
        data: expect.any(String),
      }),
    )
    const options = lastRequest()
    expect(JSON.parse(options.data as string)).toMatchObject({ channel: 'web', ...payload })
  }

  await agentsApi.command('session', '/stop', 'stop-id')
  const options = lastRequest()
  expect(JSON.parse(options.data as string)).toEqual({
    channel: 'web',
    session: 'session',
    text: '/stop',
    request_id: 'stop-id',
  })
})
