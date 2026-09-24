<script setup lang="ts">
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import AppLayout from '@/app/layout/AppLayout.vue'
</script>
<template>
  <el-config-provider :locale="zhCn">
    <AppLayout>
      <router-view v-slot="{ Component, route }">
        <component :is="Component" :key="route.path" />
      </router-view>
    </AppLayout>
  </el-config-provider>
</template>
