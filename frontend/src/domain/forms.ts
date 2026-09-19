export const idRule = {
  required: true,
  pattern: /^[A-Za-z0-9_-]{1,80}$/,
  message: '请输入 1–80 位字母、数字、下划线或短横线',
  trigger: 'blur',
}
export const sourcePolicies = [
  { value: 'stop', label: '停止' },
  { value: 'notice', label: '提示' },
  { value: 'skip', label: '跳过' },
] as const
