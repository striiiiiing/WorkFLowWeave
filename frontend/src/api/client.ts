import type { ErrorInfo } from '@/types'

export class ApiError extends Error {
  public code: string
  public status: number
  public details?: Record<string, any>

  constructor(status: number, message: string, code = 'API_ERROR', details?: Record<string, any>) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

// [Design Decision DEC-SEC-01] 统一网络层封装，拦截处理与脱敏错误映射
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = path.startsWith('/') ? path : `/${path}`
  
  const headers = new Headers(options.headers || {})
  if (!headers.has('Content-Type') && options.body && typeof options.body === 'string') {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(url, {
    ...options,
    headers,
  })

  if (!response.ok) {
    let errorData: Partial<ErrorInfo> = {}
    try {
      errorData = await response.json()
    } catch {
      errorData = {
        code: `HTTP_${response.status}`,
        message: response.statusText || '请求异常',
      }
    }

    // 对齐交互模块错误码映射 (422 校验失败, 409 冲突, 429 容量已满, 503 未就绪)
    throw new ApiError(
      response.status,
      errorData.message || `请求失败 (${response.status})`,
      errorData.code || `HTTP_${response.status}`,
      errorData.details
    )
  }

  if (response.status === 204) {
    return {} as T
  }

  return response.json()
}
