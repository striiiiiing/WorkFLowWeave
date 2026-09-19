<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import AppNavigation from './AppNavigation.vue'
import AppIcon from '@/components/icons/AppIcon.vue'
import { navigation } from '@/router/navigation'
const route = useRoute()
const collapsed = ref(false)
const drawer = ref(false)
const dark = ref(document.documentElement.classList.contains('dark'))
const title = computed(
  () =>
    navigation.find((item) => item.path === '/' + (route.path.split('/')[1] ?? ''))?.title ??
    '页面未找到',
)
function toggleTheme() {
  dark.value = !dark.value
  document.documentElement.classList.toggle('dark', dark.value)
  localStorage.setItem('logagent_theme', dark.value ? 'dark' : 'light')
}
</script>
<template>
  <div class="app-shell">
    <aside class="desktop-sidebar" :class="{ collapsed }">
      <router-link to="/" class="brand">
        <span class="brand-mark">L</span>
        <span v-if="!collapsed">
          <strong>LogAgent</strong>
          <small>采集与 AI 分析工作流</small>
        </span>
      </router-link>
      <AppNavigation :collapsed="collapsed" />
    </aside>
    <el-drawer v-model="drawer" title="LogAgent 导航" direction="ltr" size="260px">
      <AppNavigation @navigate="drawer = false" />
    </el-drawer>
    <div class="app-main">
      <header class="topbar">
        <div class="flex items-center gap-3 min-w-0">
          <el-button
            class="desktop-toggle"
            text
            aria-label="折叠侧栏"
            @click="collapsed = !collapsed"
          >
            <AppIcon name="menu" />
          </el-button>
          <el-button class="mobile-toggle" text aria-label="打开导航" @click="drawer = true">
            <AppIcon name="menu" />
          </el-button>
          <span class="muted text-sm">
            首页 /
            <span class="text-current">{{ title }}</span>
          </span>
        </div>
        <div class="flex items-center gap-2">
          <el-button text :aria-label="dark ? '切换浅色模式' : '切换深色模式'" @click="toggleTheme">
            <AppIcon :name="dark ? 'sun' : 'moon'" />
          </el-button>
          <router-link to="/workflows/new">
            <el-button type="primary" size="small">新建工作流</el-button>
          </router-link>
        </div>
      </header>
      <main class="page-content"><slot /></main>
    </div>
  </div>
</template>
