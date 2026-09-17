<template>
  <div class="min-h-screen bg-slate-50 dark:bg-slate-900 flex flex-col lg:flex-row text-slate-900 dark:text-slate-100">
    <!-- [Design Decision DEC-LAYOUT-01 & DEC-LAYOUT-02] 移动端顶部导航栏 -->
    <header class="lg:hidden flex items-center justify-between px-4 py-3 bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 sticky top-0 z-30">
      <div class="flex items-center gap-2">
        <button
          type="button"
          class="p-2 -ml-2 text-slate-600 dark:text-slate-300 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 min-h-[44px] min-w-[44px] flex items-center justify-center"
          aria-label="打开菜单"
          @click="mobileDrawerOpen = true"
        >
          <AppIcon name="menu" size="md" />
        </button>
        <span class="font-bold text-base tracking-tight text-blue-600 dark:text-blue-400">
          LogAgent
        </span>
      </div>

      <div class="flex items-center gap-2">
        <!-- 暗黑模式切换 -->
        <button
          type="button"
          class="p-2 text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 rounded-lg min-h-[44px] min-w-[44px] flex items-center justify-center"
          aria-label="切换主题"
          @click="toggleDarkMode"
        >
          <span class="text-xs font-semibold">{{ isDark ? '🌙' : '☀️' }}</span>
        </button>
      </div>
    </header>

    <!-- [Design Decision DEC-LAYOUT-01] 桌面端固定侧边栏 -->
    <aside class="hidden lg:flex flex-col w-60 bg-white dark:bg-slate-800 border-r border-slate-200 dark:border-slate-700 shrink-0 h-screen sticky top-0">
      <!-- 品牌标识 -->
      <div class="px-6 py-5 border-b border-slate-100 dark:border-slate-700 flex items-center justify-between">
        <div>
          <h1 class="font-bold text-lg text-blue-600 dark:text-blue-400 flex items-center gap-2">
            <AppIcon name="workflow" size="md" />
            LogAgent
          </h1>
          <p class="text-xs text-slate-400 mt-0.5">采集与 AI 分析工作流</p>
        </div>
      </div>

      <!-- 导航项列表 -->
      <nav class="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          :class="[
            'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors min-h-[44px]',
            isRouteActive(item.path)
              ? 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400 font-semibold'
              : 'text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/50'
          ]"
        >
          <AppIcon :name="item.icon" size="sm" />
          {{ item.name }}
        </router-link>
      </nav>

      <!-- 底部系统健康度与主题切换 -->
      <div class="p-4 border-t border-slate-100 dark:border-slate-700 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
        <div class="flex items-center gap-1.5">
          <span class="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
          <span>服务正常</span>
        </div>
        <button
          type="button"
          class="p-1.5 rounded hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 min-h-[36px] min-w-[36px] flex items-center justify-center"
          title="切换深色/浅色模式"
          @click="toggleDarkMode"
        >
          {{ isDark ? '🌙 暗色' : '☀️ 亮色' }}
        </button>
      </div>
    </aside>

    <!-- [Design Decision DEC-LAYOUT-02] 移动端滑动抽屉 -->
    <div v-if="mobileDrawerOpen" class="lg:hidden fixed inset-0 z-40 flex">
      <!-- 遮罩 -->
      <div
        class="fixed inset-0 bg-slate-900/50 backdrop-blur-sm transition-opacity"
        @click="mobileDrawerOpen = false"
      />
      <!-- 抽屉菜单 -->
      <div class="relative flex-1 flex flex-col max-w-xs w-full bg-white dark:bg-slate-800 border-r border-slate-200 dark:border-slate-700 z-50 p-4">
        <div class="flex items-center justify-between pb-4 border-b border-slate-100 dark:border-slate-700">
          <span class="font-bold text-lg text-blue-600 dark:text-blue-400">LogAgent</span>
          <button
            type="button"
            class="p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded-lg min-h-[44px] min-w-[44px] flex items-center justify-center"
            @click="mobileDrawerOpen = false"
          >
            <AppIcon name="x" size="sm" />
          </button>
        </div>

        <nav class="flex-1 py-4 space-y-1 overflow-y-auto">
          <router-link
            v-for="item in navItems"
            :key="item.path"
            :to="item.path"
            :class="[
              'flex items-center gap-3 px-3 py-3 rounded-lg text-sm font-medium transition-colors min-h-[44px]',
              isRouteActive(item.path)
                ? 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400 font-semibold'
                : 'text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700'
            ]"
            @click="mobileDrawerOpen = false"
          >
            <AppIcon :name="item.icon" size="sm" />
            {{ item.name }}
          </router-link>
        </nav>
      </div>
    </div>

    <!-- 主工作区内容 -->
    <main class="flex-1 flex flex-col overflow-y-auto min-h-0">
      <div class="max-w-7xl w-full mx-auto p-4 sm:p-6 lg:p-8 flex-1">
        <slot />
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from '@/components/icons/AppIcon.vue'

const route = useRoute()
const mobileDrawerOpen = ref(false)
const isDark = ref(false)

const navItems = [
  { name: '监控总览', path: '/', icon: 'workflow' },
  { name: '工作流管理', path: '/workflows', icon: 'workflow' },
  { name: '运行记录', path: '/runs', icon: 'play' },
  { name: '资源配置', path: '/resources', icon: 'database' },
  { name: '插件与能力', path: '/plugins', icon: 'cpu' },
]

function isRouteActive(path: string) {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

function toggleDarkMode() {
  isDark.value = !isDark.value
  if (isDark.value) {
    document.documentElement.classList.add('dark')
  } else {
    document.documentElement.classList.remove('dark')
  }
}
</script>
