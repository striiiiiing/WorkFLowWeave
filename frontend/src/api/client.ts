import type { ErrorInfo } from '@/types'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly info: ErrorInfo,
  ) {
    super(info.message)
    this.name = 'ApiError'
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError && Array.isArray(error.info.details.errors)) {
    const issues = error.info.details.errors.flatMap((issue) => {
      if (!issue || typeof issue !== 'object' || Array.isArray(issue)) return []
      return Array.isArray(issue.path) && typeof issue.reason === 'string'
        ? [`${issue.path.join('.')}: ${issue.reason}`]
        : []
    })
    return [error.message, ...issues].join('；')
  }
  return error instanceof Error ? error.message : String(error)
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

export async function request<T>(
  path: string,
  options: RequestInit = {},
  acceptedStatuses: number[] = [],
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...options.headers,
    },
  })
  if (response.status === 204) return undefined as T
  const httpError = () =>
    new ApiError(response.status, {
      code: 'http_error',
      message:
        response.status === 405
          ? `LogAgent 接口不支持 ${options.method ?? 'GET'} /api${path}（HTTP 405）；请确认后端已更新并重启，且 /api 代理指向 LogAgent 服务`
          : `LogAgent 请求失败（HTTP ${response.status}）：${options.method ?? 'GET'} /api${path}`,

      details: {
        path: `/api${path}`,
        status_text: response.statusText,
        content_type: response.headers.get('content-type'),
      },
    })
  const text = await response.text()
  let body: unknown
  try {
    body = JSON.parse(text)
  } catch {
    if (!response.ok) throw httpError()
    throw new Error(`服务返回了无效 JSON（HTTP ${response.status}）`)
  }
  if (body && typeof body === 'object' && 'error' in body && isErrorInfo(body.error)) {
    throw new ApiError(response.status, body.error)
  }
  if (!response.ok && !acceptedStatuses.includes(response.status)) {
    throw httpError()
  }
  return body as T
}

export const segment = (value: string) => encodeURIComponent(value)
