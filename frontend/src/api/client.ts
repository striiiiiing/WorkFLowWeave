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
            ? [formatValidationIssue(issue.path, issue.reason)]
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

const fieldLabels: Record<string, string> = {
  id: '编号',
  name: '名称',
  collector: '采集器',
  channel: '渠道',
  workflow_id: '工作流',
  sources: '数据来源',
  channels: '通知渠道',
  options: '选项',
  setters: '处理规则',
  timeout: '超时时间',
  retries: '重试次数',
  analyses: '分析任务',
  ai: '供应商渠道',
  model: '模型',
  prompt: '提示词',
  fan_in: '汇总设置',
  order: '汇总顺序',
  source_overrides: '数据来源的本次设置',
  channel_overrides: '通知渠道的本次设置',
  recipient: '收件人',
  sender: '发件人',
  host: '服务器地址',
  port: '端口',
  username: '账号',
  password: '凭据',
  api_key: 'API 密钥',
  base_url: '服务地址',
  after: '起始时间',
  before: '截止时间',
  limit: '每页数量',
  offset: '分页位置',
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
function formatValidationIssue(path: unknown[], reason: string): string {
  const readable = path
    .filter((part) => !['body', 'query', 'path'].includes(String(part)))
    .map((part) =>
      typeof part === 'number' ? `第 ${part + 1} 项` : (fieldLabels[String(part)] ?? String(part)),
    )
    .join(' → ')
  return `${readable || '配置'}：${reasonLabels[reason] ?? `不符合要求（${reason}）`}`
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
  if (
    !response.ok &&
    body &&
    typeof body === 'object' &&
    'error' in body &&
    isErrorInfo(body.error)
  ) {
    throw new ApiError(response.status, body.error)
  }
  if (!response.ok && !acceptedStatuses.includes(response.status)) {
    throw httpError()
  }
  return body as T
}

export const segment = (value: string) => encodeURIComponent(value)
