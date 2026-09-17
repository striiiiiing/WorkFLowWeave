import { defineStore } from 'pinia'
import { ref } from 'vue'
import { resourcesApi } from '@/api/resources'
import type {
  SourceConfig,
  SetterTemplate,
  AIConfig,
  ChannelConfig,
  Credential,
  ID,
} from '@/types'

export const useResourceStore = defineStore('resource', () => {
  const sources = ref<SourceConfig[]>([])
  const setterTemplates = ref<SetterTemplate[]>([])
  const ais = ref<AIConfig[]>([])
  const channels = ref<ChannelConfig[]>([])
  const credentials = ref<Credential[]>([])
  const loading = ref(false)

  async function fetchAllResources() {
    loading.value = true
    try {
      const [srcRes, tplRes, aiRes, chRes, credRes] = await Promise.all([
        resourcesApi.listSources().catch(() => []),
        resourcesApi.listSetterTemplates().catch(() => []),
        resourcesApi.listAIs().catch(() => []),
        resourcesApi.listChannels().catch(() => []),
        resourcesApi.listCredentials().catch(() => []),
      ])
      sources.value = srcRes
      setterTemplates.value = tplRes
      ais.value = aiRes
      channels.value = chRes
      credentials.value = credRes
    } finally {
      loading.value = false
    }
  }

  async function saveSource(src: SourceConfig) {
    const res = await resourcesApi.saveSource(src)
    const idx = sources.value.findIndex((s) => s.id === res.id)
    if (idx >= 0) sources.value[idx] = res
    else sources.value.push(res)
    return res
  }

  async function deleteSource(id: ID) {
    await resourcesApi.deleteSource(id)
    sources.value = sources.value.filter((s) => s.id !== id)
  }

  async function saveAI(ai: AIConfig) {
    const res = await resourcesApi.saveAI(ai)
    const idx = ais.value.findIndex((a) => a.id === res.id)
    if (idx >= 0) ais.value[idx] = res
    else ais.value.push(res)
    return res
  }

  async function deleteAI(id: ID) {
    await resourcesApi.deleteAI(id)
    ais.value = ais.value.filter((a) => a.id !== id)
  }

  async function saveChannel(ch: ChannelConfig) {
    const res = await resourcesApi.saveChannel(ch)
    const idx = channels.value.findIndex((c) => c.id === res.id)
    if (idx >= 0) channels.value[idx] = res
    else channels.value.push(res)
    return res
  }

  async function deleteChannel(id: ID) {
    await resourcesApi.deleteChannel(id)
    channels.value = channels.value.filter((c) => c.id !== id)
  }

  async function saveCredential(cred: Credential) {
    const res = await resourcesApi.saveCredential(cred)
    const idx = credentials.value.findIndex((c) => c.id === res.id)
    if (idx >= 0) credentials.value[idx] = res
    else credentials.value.push(res)
    return res
  }

  return {
    sources,
    setterTemplates,
    ais,
    channels,
    credentials,
    loading,
    fetchAllResources,
    saveSource,
    deleteSource,
    saveAI,
    deleteAI,
    saveChannel,
    deleteChannel,
    saveCredential,
  }
})
