import { useWorkflowList } from '@/modules/workflows/public'
import { useRecentRuns } from '@/modules/runs/public'
import { useSystemDiagnostics } from '@/modules/system/public'
export function useDashboard() {
  const workflows = useWorkflowList()
  const sessions = useRecentRuns()
  const system = useSystemDiagnostics()
  async function refreshAll() {
    await Promise.all([workflows.refresh(), sessions.refresh(), system.refresh()])
  }
  return { workflows, sessions, system, refreshAll }
}
export type DashboardController = ReturnType<typeof useDashboard>
