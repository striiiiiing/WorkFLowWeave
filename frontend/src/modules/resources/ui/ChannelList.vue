<script setup lang="ts">
import type { ChannelConfig } from '../model/public'
import AppIcon from '@/shared/ui/icons/AppIcon.vue'
defineProps<{
  resources: readonly ChannelConfig[]
  pending: boolean
  busy: boolean
  error: string
}>()
const emit = defineEmits<{ edit: [value: ChannelConfig]; remove: [id: string] }>()
</script>
<template>
  <div v-loading="pending" class="grid grid-cols-1 md:grid-cols-2 gap-4">
    <el-card v-for="resource in resources" :key="resource.id" shadow="never">
      <div class="flex items-start gap-3">
        <AppIcon name="mail" />
        <div class="min-w-0">
          <h2 class="font-semibold mono break-all">{{ resource.id }}</h2>
          <p class="muted text-sm mt-2">{{ resource.channel }}</p>
        </div>
      </div>
      <div class="flex justify-end gap-2 mt-5">
        <el-button @click="emit('edit', resource)">编辑</el-button>
        <el-popconfirm title="确认删除此资源？" @confirm="emit('remove', resource.id)">
          <template #reference>
            <el-button type="danger" plain :disabled="busy">删除</el-button>
          </template>
        </el-popconfirm>
      </div>
    </el-card>
  </div>
  <el-empty v-if="!pending && !error && !resources.length" description="此分类暂无资源" />
</template>
