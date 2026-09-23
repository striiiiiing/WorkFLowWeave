import type { IconName } from '@/components/icons/registry'
export const navigation = [
  { path: '/', title: '监控总览', icon: 'dashboard' },
  { path: '/workflows', title: '工作流管理', icon: 'workflow' },
  { path: '/runs', title: '运行记录', icon: 'play' },
  { path: '/resources', title: '资源配置', icon: 'database' },
  { path: '/collector-demo', title: '数据源配置演示', icon: 'database' },
  { path: '/plugins', title: '插件与能力', icon: 'cpu' },
  { path: '/agents', title: 'Agent 会话', icon: 'bot' },
  { path: '/agent-demo', title: 'Agent 交互演示', icon: 'sparkles' },
] as const satisfies ReadonlyArray<{ path: string; title: string; icon: IconName }>
