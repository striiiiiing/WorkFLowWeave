import { useWorkflowList } from '@/modules/workflows/public'
import { useRecentRuns } from '@/modules/runs/public'
import { useSystemHealth } from '@/modules/system/public'
export function useDashboard() {
  const workflows = useWorkflowList()
  const sessions = useRecentRuns()
  const health = useSystemHealth()
  async function refreshAll() {
    await Promise.all([workflows.refresh(), sessions.refresh(), health.refresh()])
  }
  return { workflows, sessions, health, refreshAll }
}
export type DashboardController = ReturnType<typeof useDashboard>
