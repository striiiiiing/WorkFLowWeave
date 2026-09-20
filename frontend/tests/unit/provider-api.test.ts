import { afterEach, describe, expect, it, vi } from 'vitest'
import { resourcesApi } from '@/api/resources'

afterEach(() => vi.unstubAllGlobals())
describe('provider HTTP actions', () => {
  it('reports a stale credential route with its actual local path', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('{"detail":"Method Not Allowed"}', { status: 405 })),
    )
    await expect(resourcesApi.protectCredential('test-only')).rejects.toThrow(
      'POST /api/credentials/protect（HTTP 405）',
    )
  })
  it('only invokes the explicit check endpoint', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('["model-a"]'))
    vi.stubGlobal('fetch', fetcher)
    await expect(resourcesApi.checkAIConnection('provider')).resolves.toEqual(['model-a'])
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher).toHaveBeenCalledWith(
      '/api/ai/provider/check-connection',
      expect.objectContaining({ method: 'POST' }),
    )
  })
})
