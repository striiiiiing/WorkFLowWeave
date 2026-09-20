/**
 * API 客户端单元测试：用受控 fetch 响应验证请求、响应解析和结构化错误传播；不启动真实后端。
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, errorMessage } from '@/api/client'
import { resourcesApi } from '@/api/resources'
import { runsApi } from '@/api/runs'
import { systemApi } from '@/api/system'

afterEach(() => vi.unstubAllGlobals())
function respond(body: unknown, status = 200) {
  const fetcher = vi
    .fn()
    .mockResolvedValue(new Response(status === 204 ? null : JSON.stringify(body), { status }))
  vi.stubGlobal('fetch', fetcher)
  return fetcher
}
describe('HTTP contract', () => {
  it('uses resource endpoints directly and handles 204 deletes', async () => {
    const fetcher = respond(null, 204)
    await expect(resourcesApi.delete('sources', 'source a')).resolves.toBeUndefined()
    expect(fetcher).toHaveBeenCalledWith(
      '/api/sources/source%20a',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })
  it('requests stage content at an explicit immutable version', async () => {
    const fetcher = respond({ version: 7 })
    await runsApi.phase('run_1', 'aggregate', 7)
    expect(fetcher).toHaveBeenCalledWith(
      '/api/sessions/run_1/phases/aggregate?version=7',
      expect.any(Object),
    )
  })
  it('preserves declined cancellation responses', async () => {
    respond({ session_id: 'run_1', cancelled: false })
    expect((await runsApi.cancel('run_1')).cancelled).toBe(false)
  })
  it('surfaces server validation paths instead of treating failure as empty data', async () => {
    respond(
      {
        error: {
          code: 'validation',
          message: '无效配置',
          details: { errors: [{ path: ['body', 'analyses'], reason: 'too_short' }] },
        },
      },
      422,
    )
    const error = await resourcesApi.list('workflows').catch((cause) => cause)
    expect(error).toBeInstanceOf(ApiError)
    expect(errorMessage(error)).toBe('无效配置；body.analyses: too_short')
  })
  it('reads an unavailable health report from HTTP 503', async () => {
    respond({ status: 'unavailable', accepting_runs: false, components: [] }, 503)
    expect((await systemApi.health()).status).toBe('unavailable')
  })
  it('does not accept 503 on ordinary data endpoints', async () => {
    respond({ error: { code: 'not_ready', message: '服务未就绪', details: {} } }, 503)
    await expect(resourcesApi.list('sources')).rejects.toThrow('服务未就绪')
  })
  it.each([
    ['', 500],
    ['<html>Bad Gateway</html>', 502],
    ['', 503],
  ])('preserves non-JSON HTTP errors (%s, %i)', async (body, status) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { status })))
    const error = await systemApi.health().catch((cause) => cause)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(status)
    expect(error.message).toContain(`HTTP ${status}`)
    expect(error.message).not.toContain('无效 JSON')
  })
  it('rejects a health error envelope even though 503 reports are accepted', async () => {
    respond({ error: { code: 'not_ready', message: '服务未就绪', details: {} } }, 503)
    await expect(systemApi.health()).rejects.toThrow('服务未就绪')
  })
  it('reports invalid successful JSON explicitly', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html></html>')))
    await expect(resourcesApi.list('sources')).rejects.toThrow('服务返回了无效 JSON（HTTP 200）')
  })
  it.each([null, { error: 'unexpected error format' }])(
    'preserves HTTP status when the error body has an unexpected shape',
    async (body) => {
      respond(body, 500)
      const error = await resourcesApi.list('sources').catch((cause) => cause)
      expect(error).toBeInstanceOf(ApiError)
      expect(error.status).toBe(500)
    },
  )
})
