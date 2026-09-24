import axios, { AxiosError } from 'axios'
import { describe, expect, it } from 'vitest'
import { ApiError, NetworkError, RequestCancelledError } from '@/shared/api'
import { createHttpHarness } from '../helpers/httpHarness'

describe('Axios adapter transport contract', () => {
  it('serializes JSON once and retains false, zero, empty text, headers and signal', async () => {
    const { http, respond, lastRequest, lastUrl } = createHttpHarness()
    respond({ accepted: true })
    const signal = new AbortController().signal
    const data = { text: '中文', enabled: false, nested: { value: 0 } }
    await http.request({
      url: '/contract',
      method: 'PUT',
      data,
      params: { offset: 0, enabled: false, value: '', absent: undefined },
      headers: { 'If-Match': '"previous"', 'If-None-Match': '*' },
      signal,
    })
    const request = lastRequest()
    expect(request.data).toBe(JSON.stringify(data))
    expect(JSON.parse(request.data)).toEqual(data)
    expect(request.headers.get('If-Match')).toBe('"previous"')
    expect(request.headers.get('If-None-Match')).toBe('*')
    expect(request.signal).toBe(signal)
    expect(request.timeout).toBe(0)
    expect(request.baseURL).toBe('/api')
    expect(Object.fromEntries(new URL(lastUrl(), 'http://local').searchParams)).toEqual({
      offset: '0',
      enabled: 'false',
      value: '',
    })
  })

  it('rejects an aborted request even when an adapter later resolves', async () => {
    const { http, adapter } = createHttpHarness()
    const controller = new AbortController()
    let finish!: () => void
    adapter.mockImplementation(
      (config) =>
        new Promise((resolve) => {
          finish = () =>
            resolve({
              config,
              status: 200,
              statusText: 'OK',
              headers: { 'content-type': 'application/json' },
              data: '{}',
            })
        }),
    )
    const pending = http.request({ url: '/write', method: 'POST', signal: controller.signal })
    controller.abort()
    finish()
    await expect(pending).rejects.toBeInstanceOf(RequestCancelledError)
    expect(adapter).toHaveBeenCalledTimes(1)
  })

  it('keeps network errors separate from cancellation and never retries', async () => {
    const { http, adapter } = createHttpHarness()
    adapter.mockRejectedValue(new AxiosError('offline', AxiosError.ERR_NETWORK))
    await expect(http.request({ url: '/write', method: 'POST' })).rejects.toBeInstanceOf(
      NetworkError,
    )
    expect(adapter).toHaveBeenCalledTimes(1)
    adapter.mockRejectedValue(new axios.CanceledError())
    await expect(http.request({ url: '/write', method: 'POST' })).rejects.toBeInstanceOf(
      RequestCancelledError,
    )
    expect(adapter).toHaveBeenCalledTimes(2)
  })

  it.each([{}, { message: 'down' }, { code: 'down', message: 'down', details: [] }])(
    'rejects malformed nested health errors: %j',
    async (error) => {
      const { systemApi, respond } = createHttpHarness()
      respond(
        {
          status: 'unavailable',
          accepting_runs: false,
          checked_at: 'now',
          components: [
            {
              component: 'storage',
              status: 'unavailable',
              required: true,
              checked_at: null,
              error,
            },
          ],
        },
        503,
      )
      await expect(systemApi.health()).rejects.toBeInstanceOf(ApiError)
    },
  )

  it('accepts complete nested health errors as part of the report', async () => {
    const { systemApi, respond } = createHttpHarness()
    const report = {
      status: 'unavailable',
      accepting_runs: false,
      checked_at: 'now',
      components: [
        {
          component: 'storage',
          status: 'unavailable',
          required: true,
          checked_at: null,
          error: { code: 'down', message: 'down', details: {} },
        },
      ],
    }
    respond(report, 503)
    expect(await systemApi.health()).toEqual(report)
  })

  it('preserves saved workflow run endpoint, path encoding and AbortSignal', async () => {
    const { runsApi, respond, lastRequest } = createHttpHarness()
    respond({ session_id: 'run' }, 202)
    const signal = new AbortController().signal
    expect(await runsApi.trigger('workflow a', signal)).toEqual({ session_id: 'run' })
    expect(lastRequest()).toMatchObject({
      url: '/workflows/workflow%20a/run',
      method: 'post',
      signal,
    })
    expect(lastRequest().data).toBeUndefined()
  })
})
