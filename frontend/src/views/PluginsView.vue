<template>
  <div class="space-y-6">
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <div>
        <h2 class="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
          插件能力与 Schema 浏览器 (Plugins)
        </h2>
        <p class="text-sm text-slate-500 dark:text-slate-400 mt-1">
          查看已动态发现与注册的 Collector 及 Channel 扩展能力与 JSON Schema 约束
        </p>
      </div>

      <div class="flex items-center gap-3">
        <Button variant="secondary" icon="rotate-ccw" :loading="reloading" @click="handleReload">
          热重载插件 (Reload)
        </Button>
      </div>
    </div>

    <div v-if="systemStore.loading" class="p-12 text-center text-slate-400">
      <AppIcon name="loader" :spin="true" class="mx-auto mb-2" size="lg" />
      <span>加载插件目录能力中...</span>
    </div>

    <div v-else-if="systemStore.plugins.length === 0" class="p-12 text-center border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-xl text-slate-400 text-sm">
      未发现已加载的插件扩展
    </div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-5">
      <Card
        v-for="plugin in systemStore.plugins"
        :key="plugin.id"
        :title="plugin.id"
        :subtitle="`类型: ${plugin.kind.toUpperCase()} • 版本: v${plugin.version}`"
        :icon="plugin.kind === 'collector' ? 'database' : 'mail'"
      >
        <template #header-actions>
          <span class="px-2 py-0.5 rounded text-[11px] font-mono bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300">
            {{ plugin.owner || 'system' }}
          </span>
        </template>

        <div class="space-y-3 text-xs">
          <p v-if="plugin.description" class="text-slate-600 dark:text-slate-300">
            {{ plugin.description }}
          </p>

          <div v-if="plugin.fields && plugin.fields.length > 0">
            <span class="text-slate-400 font-semibold">支持字段:</span>
            <div class="flex flex-wrap gap-1 mt-1">
              <span
                v-for="f in plugin.fields"
                :key="f"
                class="px-1.5 py-0.5 bg-slate-100 dark:bg-slate-700/60 rounded font-mono text-[11px]"
              >
                {{ f }}
              </span>
            </div>
          </div>

          <!-- JSON Schema 展开区 -->
          <div>
            <span class="text-slate-400 font-semibold">配置选项 Schema (options_schema):</span>
            <pre class="mt-1 p-3 bg-slate-900 text-slate-100 rounded-lg font-mono text-[11px] max-h-48 overflow-y-auto selection:bg-blue-600">{{ JSON.stringify(plugin.options_schema, null, 2) }}</pre>
          </div>
        </div>
      </Card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import Card from '@/components/common/Card.vue'
import Button from '@/components/common/Button.vue'
import AppIcon from '@/components/icons/AppIcon.vue'
import { useSystemStore } from '@/stores/systemStore'

const systemStore = useSystemStore()
const reloading = ref(false)

async function handleReload() {
  reloading.value = true
  try {
    await systemStore.reloadSystem()
    alert('插件热重载成功！')
  } catch (err: any) {
    alert(`重载失败: ${err.message}`)
  } finally {
    reloading.value = false
  }
}

onMounted(() => {
  systemStore.fetchPlugins()
})
</script>
