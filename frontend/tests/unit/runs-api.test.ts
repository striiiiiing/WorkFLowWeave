import { afterEach, expect, it, vi } from 'vitest'
import { runsApi } from '@/api/runs'

afterEach(() => vi.unstubAllGlobals())

it('encodes field filters without emitting empty or undefined values', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response('[]'))
  vi.stubGlobal('fetch', fetcher)
  await runsApi.list({
    workflow_name: '日报 & Weekly',
    workflow_id: '',
    session_id: undefined,
    status: 'failed',
    limit: 20,
    offset: 0,
  })
  const url = new URL(fetcher.mock.calls[0][0], 'http://localhost')
  expect(Object.fromEntries(url.searchParams)).toEqual({
    workflow_name: '日报 & Weekly',
    status: 'failed',
    limit: '20',
    offset: '0',
  })
})
