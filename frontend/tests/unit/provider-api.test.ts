import { describe, expect, it } from 'vitest'
import { createHttpHarness } from '../helpers/httpHarness'

describe('provider HTTP actions', () => {
  it('reports a stale credential route with its actual local path', async () => {
    const { resourcesApi, respond } = createHttpHarness()
    respond({ detail: 'Method Not Allowed' }, 405)
    await expect(resourcesApi.protectCredential('test-only')).rejects.toThrow(
      'POST /api/credentials/protect（HTTP 405）',
    )
  })
  it('only invokes the explicit check endpoint', async () => {
    const { resourcesApi, respond } = createHttpHarness()
    const adapter = respond(['model-a'])
    await expect(resourcesApi.checkAIConnection('provider')).resolves.toEqual(['model-a'])
    expect(adapter).toHaveBeenCalledTimes(1)
    expect(adapter).toHaveBeenCalledWith(
      expect.objectContaining({
        url: '/ai/provider/check-connection',
        method: 'post',
      }),
    )
  })
})
