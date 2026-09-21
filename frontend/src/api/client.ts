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
  if (error instanceof ApiError) {
    const details = error.info.details
    const issues = Array.isArray(details.errors)
      ? details.errors.flatMap((issue) => {
          if (!issue || typeof issue !== 'object' || Array.isArray(issue)) return []
          return Array.isArray(issue.path) && typeof issue.reason === 'string'
            ? [`${issue.path.join('.')}: ${issue.reason}`]
            : []
        })
      : []
    const field = typeof details.field === 'string' ? `字段 ${details.field}` : ''
    const available = Array.isArray(details.available)
      ? `可用格式：${details.available.filter((item) => typeof item === 'string').join('、')}`
      : ''
    const fields = Array.isArray(details.fields)
      ? `相关字段：${details.fields.filter((item) => typeof item === 'string').join('、')}`
      : ''
    const reason = typeof details.reason === 'string' ? `原因 ${details.reason}` : ''
    const exceptionType =
      typeof details.exception_type === 'string' ? details.exception_type : undefined
    const staleBusinessError =
      error.info.code === 'invalid_config' &&
      error.message === '资源未通过业务校验' &&
      exceptionType === 'LogAgentError'
        ? '后端未展开具体校验原因，请重启后端服务后重试'
        : ''
    const code = staleBusinessError ? `错误码 ${error.info.code}` : ''
    const exception = exceptionType && !staleBusinessError ? `异常类型 ${exceptionType}` : ''
    return [
      error.message,
      code,
      field,
      available,
      fields,
      reason,
      exception,
      staleBusinessError,
      ...issues,
    ]
      .filter(Boolean)
      .join('；')
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
