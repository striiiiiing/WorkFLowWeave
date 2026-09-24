import type { ErrorInfo } from '@/shared/types'

export function isErrorInfo(value: unknown): value is ErrorInfo {
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

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly info: ErrorInfo,
    public readonly path?: string,
  ) {
    super(info.message)
    this.name = 'ApiError'
  }
}

export function errorMessage(
  error: unknown,
  fieldLabels: Readonly<Record<string, string>> = {},
): string {
  if (error instanceof ApiError) {
    const details = error.info.details
    const issues = Array.isArray(details.errors)
      ? details.errors.flatMap((issue) => {
          if (!issue || typeof issue !== 'object' || Array.isArray(issue)) return []
          return Array.isArray(issue.path) && typeof issue.reason === 'string'
            ? [formatValidationIssue(issue.path, issue.reason, fieldLabels)]
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

const reasonLabels: Record<string, string> = {
  missing: '请填写此项',
  required: '请填写此项',
  too_short: '内容太少，请补充完整',
  too_long: '内容太多，请减少后再试',
  string_type: '请输入文字',
  int_type: '请输入整数',
  int_parsing: '请输入整数',
  float_type: '请输入数字',
  float_parsing: '请输入数字',
  bool_type: '请选择是或否',
  greater_than: '数值过小',
  greater_than_equal: '数值过小',
  less_than: '数值过大',
  less_than_equal: '数值过大',
  url_parsing: '请输入有效的网址',
  enum: '请选择列表中的选项',
  literal_error: '请选择列表中的选项',
  string_pattern_mismatch: '格式不符合要求',
  extra_forbidden: '此项不支持，请删除',
  value_error: '此项不符合要求，请检查设置',
}
function formatValidationIssue(
  path: unknown[],
  reason: string,
  fieldLabels: Readonly<Record<string, string>>,
): string {
  const readable = path
    .filter((part) => !['body', 'query', 'path'].includes(String(part)))
    .map((part) =>
      typeof part === 'number' ? `第 ${part + 1} 项` : (fieldLabels[String(part)] ?? String(part)),
    )
    .join(' → ')
  return `${readable || '配置'}：${reasonLabels[reason] ?? `不符合要求（${reason}）`}`
}

export class NetworkError extends Error {
  readonly kind = 'network'
  constructor(
    public readonly path: string,
    public readonly cause: unknown,
  ) {
    super(`无法连接 LogAgent：${path}；请求结果未知`)
    this.name = 'NetworkError'
  }
}

export class RequestCancelledError extends Error {
  readonly kind = 'cancelled'
  constructor(
    public readonly path: string,
    public readonly cause: unknown,
  ) {
    super(`请求已取消：${path}`)
    this.name = 'RequestCancelledError'
  }
}
