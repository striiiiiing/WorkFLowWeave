<template>
  <div class="space-y-6">
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <div>
        <h2 class="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
          资源配置中心 (Resources)
        </h2>
        <p class="text-sm text-slate-500 dark:text-slate-400 mt-1">
          管理可复用的数据源、AI 模型配置、通知渠道及安全凭据
        </p>
      </div>

      <Button variant="secondary" icon="rotate-ccw" @click="resourceStore.fetchAllResources">
        刷新
      </Button>
    </div>

    <!-- 资源分类切换标签 -->
    <div class="flex items-center gap-2 border-b border-slate-200 dark:border-slate-700 pb-2">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        :class="[
          'px-4 py-2 text-sm font-medium rounded-lg transition-colors min-h-[44px]',
          activeTab === tab.key
            ? 'bg-blue-600 text-white shadow-sm'
            : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
        ]"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- 标签 1: 采集源 (Sources) -->
    <div v-if="activeTab === 'sources'" class="space-y-4">
      <div class="flex justify-between items-center">
        <span class="text-xs font-bold text-slate-500 uppercase">已配置采集源 ({{ resourceStore.sources.length }})</span>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card
          v-for="src in resourceStore.sources"
          :key="src.id"
          :title="src.id"
          :subtitle="`插件: ${src.collector}`"
          icon="database"
        >
          <div class="space-y-2 text-xs">
            <div class="flex justify-between">
              <span class="text-slate-400">错误策略:</span>
              <span class="font-mono">{{ src.on_error || 'stop' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-slate-400">超时限制:</span>
              <span>{{ src.timeout ? `${src.timeout}s` : '默认' }}</span>
            </div>
            <pre class="mt-2 p-2 bg-slate-50 dark:bg-slate-900 rounded font-mono text-[11px] max-h-24 overflow-y-auto">{{ JSON.stringify(src.options, null, 2) }}</pre>
          </div>
          <template #footer>
            <Button size="sm" variant="danger" @click="deleteSource(src.id)">删除</Button>
          </template>
        </Card>
      </div>
    </div>

    <!-- 标签 2: AI 模型 (AI Configs) -->
    <div v-if="activeTab === 'ai'" class="space-y-4">
      <div class="flex justify-between items-center">
        <span class="text-xs font-bold text-slate-500 uppercase">已配置 AI 引擎 ({{ resourceStore.ais.length }})</span>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card
          v-for="ai in resourceStore.ais"
          :key="ai.id"
          :title="ai.id"
          :subtitle="`Provider: ${ai.provider}`"
          icon="bot"
        >
          <div class="space-y-2 text-xs">
            <div class="flex justify-between">
              <span class="text-slate-400">超时时间:</span>
              <span>{{ ai.timeout || 600 }}s</span>
            </div>
            <div class="flex justify-between">
              <span class="text-slate-400">重试上限:</span>
              <span>{{ ai.retries || 5 }} 次</span>
            </div>
            <div>
              <span class="text-slate-400">配置模型列表:</span>
              <div class="flex flex-wrap gap-1 mt-1">
                <span
                  v-for="modelName in Object.keys(ai.models || {})"
                  :key="modelName"
                  class="px-2 py-0.5 rounded bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300 font-mono text-[11px]"
                >
                  {{ modelName }}
                </span>
              </div>
            </div>
          </div>
          <template #footer>
            <Button size="sm" variant="danger" @click="deleteAI(ai.id)">删除</Button>
          </template>
        </Card>
      </div>
    </div>

    <!-- 标签 3: 通知渠道 (Channels) -->
    <div v-if="activeTab === 'channels'" class="space-y-4">
      <div class="flex justify-between items-center">
        <span class="text-xs font-bold text-slate-500 uppercase">已配置渠道 ({{ resourceStore.channels.length }})</span>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card
          v-for="ch in resourceStore.channels"
          :key="ch.id"
          :title="ch.id"
          :subtitle="`类型: ${ch.type}`"
          icon="mail"
        >
          <pre class="p-2 bg-slate-50 dark:bg-slate-900 rounded font-mono text-[11px] max-h-24 overflow-y-auto">{{ JSON.stringify(ch.options, null, 2) }}</pre>
          <template #footer>
            <Button size="sm" variant="danger" @click="deleteChannel(ch.id)">删除</Button>
          </template>
        </Card>
      </div>
    </div>

    <!-- 标签 4: 凭据管理 (Credentials) -->
    <div v-if="activeTab === 'credentials'" class="space-y-4">
      <div class="flex justify-between items-center">
        <span class="text-xs font-bold text-slate-500 uppercase">安全凭据存储 ({{ resourceStore.credentials.length }})</span>
      </div>

      <!-- [Design Decision DEC-SEC-01] 凭据只读掩码，不暴露明文 -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card
          v-for="cred in resourceStore.credentials"
          :key="cred.id"
          :title="cred.id"
          :subtitle="`凭据类型: ${cred.type}`"
          icon="key"
        >
          <div class="text-xs space-y-2">
            <div class="flex justify-between">
              <span class="text-slate-400">密钥引用:</span>
              <span class="font-mono text-slate-700 dark:text-slate-300">
                {{ cred.reference || '••••••••••••' }}
              </span>
            </div>
            <p class="text-slate-400 text-[11px]">
              依据设计规范，明文凭据绝不在前端控制台或界面反显，仅支持密文与环境变量安全注入。
            </p>
          </div>
        </Card>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import Card from '@/components/common/Card.vue'
import Button from '@/components/common/Button.vue'
import { useResourceStore } from '@/stores/resourceStore'

const resourceStore = useResourceStore()
const activeTab = ref<'sources' | 'ai' | 'channels' | 'credentials'>('sources')

const tabs = [
  { key: 'sources', label: '采集源 (Sources)' },
  { key: 'ai', label: 'AI 模型配置 (AI Configs)' },
  { key: 'channels', label: '通知渠道 (Channels)' },
  { key: 'credentials', label: '安全凭据 (Credentials)' },
] as const

async function deleteSource(id: string) {
  if (confirm(`确定删除数据源 ${id} 吗？`)) {
    await resourceStore.deleteSource(id)
  }
}

async function deleteAI(id: string) {
  if (confirm(`确定删除 AI 配置 ${id} 吗？`)) {
    await resourceStore.deleteAI(id)
  }
}

async function deleteChannel(id: string) {
  if (confirm(`确定删除渠道 ${id} 吗？`)) {
    await resourceStore.deleteChannel(id)
  }
}

onMounted(() => {
  resourceStore.fetchAllResources()
})
</script>
