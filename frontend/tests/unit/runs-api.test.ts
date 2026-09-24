import { expect, it } from 'vitest'
import { createHttpHarness } from '../helpers/httpHarness'

it('encodes field filters without emitting empty or undefined values', async () => {
  const { runsApi, respond, lastUrl } = createHttpHarness()
  respond([])
  await runsApi.list({
    workflow_name: '日报 & Weekly',
    workflow_id: '',
    session_id: undefined,
    status: 'failed',
    limit: 20,
    offset: 0,
  })
  const url = new URL(lastUrl(), 'http://localhost')
  expect(Object.fromEntries(url.searchParams)).toEqual({
    workflow_name: '日报 & Weekly',
    status: 'failed',
    limit: '20',
    offset: '0',
  })
})
