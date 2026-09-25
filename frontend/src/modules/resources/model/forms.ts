export { idRule } from '@/shared/schema/idRule'
export const sourcePolicies = [
  { value: 'stop', label: '停止' },
  { value: 'notice', label: '提示' },
  { value: 'skip', label: '跳过' },
] as const
