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
  it('discovers models from the supplied provider draft', async () => {
    const { resourcesApi, respond } = createHttpHarness()
    const adapter = respond(['model-a'])
    const draft = {
      id: 'provider',
      provider: 'openai_compatible_api',
      base_url: 'https://example.test/v1',
      api_key: null,
      system_prompt: '',
      models: {},
      timeout: 60,
      retries: 0,
    }
    await expect(resourcesApi.discoverAIModels(draft)).resolves.toEqual(['model-a'])
    expect(adapter).toHaveBeenCalledTimes(1)
    expect(adapter).toHaveBeenCalledWith(
      expect.objectContaining({
        url: '/ai/discover-models',
        method: 'post',
        data: JSON.stringify(draft),
      }),
    )
  })
})
