import { defineStore } from 'pinia'
import { ref } from 'vue'
import { resourcesApi } from '@/api/resources'
import type { WorkflowDefinition, ID } from '@/types'

export const useWorkflowStore = defineStore('workflow', () => {
  const workflows = ref<WorkflowDefinition[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchWorkflows() {
    loading.value = true
    error.value = null
    try {
      workflows.value = await resourcesApi.listWorkflows()
    } catch (e: any) {
      error.value = e.message || '获取工作流列表失败'
    } finally {
      loading.value = false
    }
  }

  async function getWorkflow(id: ID): Promise<WorkflowDefinition> {
    return await resourcesApi.getWorkflow(id)
  }

  async function saveWorkflow(def: WorkflowDefinition) {
    loading.value = true
    try {
      const saved = await resourcesApi.saveWorkflow(def)
      const idx = workflows.value.findIndex((w) => w.id === saved.id)
      if (idx >= 0) {
        workflows.value[idx] = saved
      } else {
        workflows.value.push(saved)
      }
      return saved
    } finally {
      loading.value = false
    }
  }

  async function deleteWorkflow(id: ID) {
    await resourcesApi.deleteWorkflow(id)
    workflows.value = workflows.value.filter((w) => w.id !== id)
  }

  return {
    workflows,
    loading,
    error,
    fetchWorkflows,
    getWorkflow,
    saveWorkflow,
    deleteWorkflow,
  }
})
