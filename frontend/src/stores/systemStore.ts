import { defineStore } from 'pinia'
import { ref } from 'vue'
import { systemApi } from '@/api/system'
import type { CapabilityDescription, SystemHealth } from '@/types'

export const useSystemStore = defineStore('system', () => {
  const plugins = ref<CapabilityDescription[]>([])
  const health = ref<SystemHealth | null>(null)
  const loading = ref(false)
  const reloadStatus = ref<string | null>(null)

  async function fetchPlugins() {
    loading.value = true
    try {
      plugins.value = await systemApi.getPlugins()
    } finally {
      loading.value = false
    }
  }

  async function fetchHealth() {
    try {
      health.value = await systemApi.getHealth()
    } catch {
      health.value = {
        status: 'degraded',
        version: '0.1.0',
        uptime_seconds: 0,
        active_runs: 0,
        max_concurrent_runs: 4,
      }
    }
  }

  async function reloadSystem() {
    loading.value = true
    try {
      const res = await systemApi.reloadSystem()
      reloadStatus.value = res.status
      await fetchPlugins()
      await fetchHealth()
      return res
    } finally {
      loading.value = false
    }
  }

  return {
    plugins,
    health,
    loading,
    reloadStatus,
    fetchPlugins,
    fetchHealth,
    reloadSystem,
  }
})
