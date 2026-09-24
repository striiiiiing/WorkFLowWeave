import axios, { type InternalAxiosRequestConfig } from 'axios'
import { vi } from 'vitest'
import { createHttpClient } from '@/shared/api'
import { createApplicationServices } from '@/app/bootstrap'

/** Controlled responses still pass through Axios request transforms and cancellation. */
export function createHttpHarness() {
  const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => ({
    config,
    status: 200,
    statusText: 'OK',
    headers: { 'content-type': 'application/json' },
    data: 'null',
  }))
  const http = createHttpClient({ adapter })
  function respond(body: unknown, status = 200) {
    adapter.mockImplementation(async (config) => ({
      config,
      status,
      statusText: String(status),
      headers: { 'content-type': 'application/json' },
      data: status === 204 ? '' : JSON.stringify(body),
    }))
    return adapter
  }
  function respondText(data: string, status = 200) {
    adapter.mockImplementation(async (config) => ({
      config,
      status,
      statusText: String(status),
      headers: { 'content-type': 'text/html' },
      data,
    }))
  }
  const lastRequest = () => adapter.mock.lastCall![0]
  const lastUrl = () => axios.getUri(lastRequest())
  return {
    http,
    adapter,
    respond,
    respondText,
    lastRequest,
    lastUrl,
    ...createApplicationServices(http),
  }
}
