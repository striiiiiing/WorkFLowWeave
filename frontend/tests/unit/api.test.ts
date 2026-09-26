/**
 * API 客户端单元测试：用受控 Axios adapter 响应验证请求、响应解析和结构化错误传播；不启动真实后端。
 */
import { describe, expect, it } from 'vitest'
import { ApiError, errorMessage } from '@/shared/api/errors'
import { errorMessage as appErrorMessage } from '@/app/errorMessage'
import { createHttpHarness } from '../helpers/httpHarness'
const { resourcesApi, workflowsApi, runsApi, systemApi, respond, respondText } = createHttpHarness()

describe('HTTP contract', () => {
  it('explains nested fields and numbered tasks in user language', () => {
    const error = new ApiError(422, {
      code: 'validation',
      message: '配置无效',
      details: {
        errors: [{ path: ['body', 'analyses', 1, 'model'], reason: 'missing' }],
      },
    })
    expect(appErrorMessage(error)).toBe('配置无效；分析任务 → 第 2 项 → 模型：请填写此项')
    expect(error.info.details.errors).toEqual([
      { path: ['body', 'analyses', 1, 'model'], reason: 'missing' },
    ])
  })
  it('uses resource endpoints directly and handles 204 deletes', async () => {
    const fetcher = respond(null, 204)
    await expect(resourcesApi.delete('sources', 'source a')).resolves.toBeUndefined()
    expect(fetcher).toHaveBeenCalledWith(
      expect.objectContaining({ url: '/sources/source%20a', method: 'delete' }),
    )
  })
  it('requests stage content at an explicit immutable version', async () => {
    const fetcher = respond({ version: 7 })
    await runsApi.phase('run_1', 'aggregate', 7)
    expect(fetcher).toHaveBeenCalledWith(
      expect.objectContaining({ url: '/sessions/run_1/phases/aggregate', params: { version: 7 } }),
    )
  })
  it('preserves declined cancellation responses', async () => {
    respond({ session_id: 'run_1', cancelled: false })
    expect((await runsApi.cancel('run_1')).cancelled).toBe(false)
  })
  it.each(['session', 'phase'])(
    'preserves errors recorded in a successful %s read',
    async (kind) => {
      const record = {
        status: 'failed',
        error: { code: 'source_stop', message: '来源策略要求停止下游阶段', details: {} },
      }
      respond(record)
      const result =
        kind === 'session' ? runsApi.get('run_1') : runsApi.phase('run_1', 'collect', 7)
      await expect(result).resolves.toEqual(record)
    },
  )
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
    const error = await workflowsApi.list().catch((cause) => cause)
    expect(error).toBeInstanceOf(ApiError)
    expect(appErrorMessage(error)).toBe('无效配置；分析任务：内容太少，请补充完整')
  })
  it('surfaces structured business validation fields', async () => {
    respond(
      {
        error: {
          code: 'provider_missing',
          message: 'API 格式不可用',
          details: { field: 'provider', available: ['OpenAI Compatible API'] },
        },
      },
      422,
    )
    const error = await resourcesApi.list('ai').catch((cause) => cause)
    expect(errorMessage(error)).toBe(
      'API 格式不可用；字段 provider；可用格式：OpenAI Compatible API',
    )
  })
  it('explains an unexpanded business error from a stale backend process', async () => {
    respond(
      {
        error: {
          code: 'invalid_config',
          message: '资源未通过业务校验',
          details: { exception_type: 'LogAgentError' },
        },
      },
      422,
    )
    const error = await resourcesApi
      .create('ai', {
        id: 'provider',
        provider: 'openai_compatible_api',
        base_url: 'http://localhost:19026/v1',
        api_key: null,
        system_prompt: '',
        models: {},
        timeout: 600,
        retries: 5,
      })
      .catch((cause) => cause)
    expect(errorMessage(error)).toBe(
      '资源未通过业务校验；错误码 invalid_config；后端未展开具体校验原因，请重启后端服务后重试',
    )
  })
  it('shows model option fields and exception type when supplied by the backend', async () => {
    respond(
      {
        error: {
          code: 'invalid_config',
          message: '模型参数无效',
          details: { fields: ['reasoning_effort'], exception_type: 'ValueError' },
        },
      },
      422,
    )
    const error = await resourcesApi.list('ai').catch((cause) => cause)
    expect(errorMessage(error)).toBe(
      '模型参数无效；相关字段：reasoning_effort；异常类型 ValueError',
    )
  })
  it('reads an unavailable health report from HTTP 503', async () => {
    respond(
      {
        status: 'unavailable',
        accepting_runs: false,
        checked_at: '2026-09-24T00:00:00Z',
        components: [],
      },
      503,
    )
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
    respondText(body, status)
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
    respondText('<html></html>')
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
