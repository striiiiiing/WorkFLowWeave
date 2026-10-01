import { shallowReadonly, shallowRef } from 'vue'
import { useAsyncTask } from '@/shared/async/useAsyncTask'
import { useSystemApi } from '../api/dependencies'
import type { SystemApi } from '../api/systemApi'
import type { DiscoveryReport } from '../model/types'
export function usePluginReload(
  refresh: () => Promise<void>,
  api: Pick<SystemApi, 'reload'> = useSystemApi(),
) {
  const task = useAsyncTask()
  const report = shallowRef<DiscoveryReport | null>()
  async function reload() {
    return task.run(async () => {
      report.value = undefined
      const result = await api.reload('plugins')
      report.value = result.report
      await refresh()
      return result
    })
  }
  return { pending: task.pending, error: task.error, report: shallowReadonly(report), reload }
}
