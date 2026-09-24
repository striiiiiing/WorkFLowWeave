import axios, { type AxiosAdapter } from 'axios'
import type { ErrorInfo } from '@/shared/types'
import { ApiError, NetworkError, RequestCancelledError } from './errors'

export interface HttpRequest {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  url: string
  params?: Record<string, string | number | boolean | null | undefined>
  data?: unknown
  headers?: Record<string, string>
  signal?: AbortSignal
  /** An endpoint may accept a non-2xx document only after validating its shape. */
  acceptResponse?: (status: number, body: unknown) => boolean
}
export interface HttpClient {
  request<T>(request: HttpRequest): Promise<T>
}
export interface HttpClientOptions {
  baseURL?: string
  adapter?: AxiosAdapter
}
function isErrorInfo(value: unknown): value is ErrorInfo {
  if (!value || typeof value !== 'object') return false
  const info = value as Partial<ErrorInfo>
  return (
    typeof info.code === 'string' &&
    typeof info.message === 'string' &&
    !!info.details &&
    typeof info.details === 'object' &&
    !Array.isArray(info.details)
  )
}

/** One Axios instance per application. No retries or implicit execution deadline. */
export function createHttpClient({
  baseURL = '/api',
  adapter,
}: HttpClientOptions = {}): HttpClient {
  const transport = axios.create({
    baseURL,
    timeout: 0,
    adapter,
    responseType: 'text',
    transformResponse: [(value: unknown) => value],
    validateStatus: () => true,
  })
  return {
    async request<T>({ acceptResponse, ...config }: HttpRequest): Promise<T> {
      const path = transport.getUri(config)
      let response
      try {
        response = await transport.request<string>(config)
      } catch (cause) {
        if (axios.isCancel(cause)) throw new RequestCancelledError(path, cause)
        if (axios.isAxiosError(cause) && !cause.response) throw new NetworkError(path, cause)
        throw cause
      }
      const { status } = response
      if (status === 204) return undefined as T
      const successful = status >= 200 && status < 300
      const httpError = () =>
        new ApiError(
          status,
          {
            code: 'http_error',
            message:
              status === 405
                ? `LogAgent 接口不支持 ${config.method ?? 'GET'} ${path}（HTTP 405）；请确认后端已更新并重启，且 /api 代理指向 LogAgent 服务`
                : `LogAgent 请求失败（HTTP ${status}）：${config.method ?? 'GET'} ${path}`,
            details: {
              path,
              status_text: response.statusText,
              content_type: String(response.headers['content-type'] ?? ''),
            },
          },
          path,
        )
      let body: unknown
      try {
        body = JSON.parse(response.data)
      } catch {
        if (!successful) throw httpError()
        throw new ApiError(
          status,
          {
            code: 'invalid_json',
            message: `服务返回了无效 JSON（HTTP ${status}）`,
            details: { path },
          },
          path,
        )
      }
      if (
        !successful &&
        body &&
        typeof body === 'object' &&
        'error' in body &&
        isErrorInfo(body.error)
      ) {
        throw new ApiError(status, body.error, path)
      }
      if (!successful && !acceptResponse?.(status, body)) throw httpError()
      return body as T
    },
  }
}
export const segment = (value: string) => encodeURIComponent(value)
