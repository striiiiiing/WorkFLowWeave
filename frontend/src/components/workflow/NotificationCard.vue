<template>
  <!-- [Design Decision DEC-LAYOUT-01] 垂直流式阶梯编排卡片：通知渠道分发阶段 -->
  <Card
    title="阶段 4：通知渠道分发 (Notification)"
    subtitle="将冻结后的最终分析结果按序发送给指定的通知平台（如邮件或本地 Mock 文件）"
    icon="mail"
  >
    <div class="space-y-4">
      <div class="flex items-center justify-between">
        <span class="text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider">
          通知目标列表 (按序投递，每渠道最多尝试一次)
        </span>
        <Button size="sm" variant="secondary" icon="plus" @click="showAddModal = true">
          添加渠道
        </Button>
      </div>

      <div v-if="workflow.channels.length === 0" class="p-6 text-center border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-lg text-slate-400 text-sm">
        暂未配置通知渠道，分析结果将仅保存在 Session 中
      </div>

      <div v-else class="space-y-2">
        <div
          v-for="(channelId, index) in workflow.channels"
          :key="channelId"
          class="flex items-center justify-between p-3 bg-white dark:bg-slate-800/80 rounded-lg border border-slate-200 dark:border-slate-700"
        >
          <div class="flex items-center gap-3">
            <span class="w-6 h-6 rounded-full bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 text-xs font-bold flex items-center justify-center">
              {{ index + 1 }}
            </span>
            <div>
              <span class="font-mono text-sm font-semibold text-slate-900 dark:text-slate-100">{{ channelId }}</span>
              <span class="ml-2 text-xs text-slate-400">已就绪</span>
            </div>
          </div>

          <div class="flex items-center gap-1">
            <button
              type="button"
              class="p-2 text-red-500 hover:text-red-700 min-h-[44px] min-w-[44px] flex items-center justify-center"
              title="移除"
              @click="removeChannel(index)"
            >
              <AppIcon name="trash" size="sm" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 添加渠道模态框 -->
    <Modal v-model="showAddModal" title="选择通知渠道">
      <div class="space-y-3">
        <div class="max-h-60 overflow-y-auto space-y-1">
          <div
            v-for="ch in availableChannels"
            :key="ch.id"
            class="flex items-center justify-between p-2.5 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700/50 cursor-pointer"
            @click="addChannel(ch.id)"
          >
            <div>
              <p class="font-mono text-sm font-medium">{{ ch.id }}</p>
              <p class="text-xs text-slate-400">类型: {{ ch.type }}</p>
            </div>
            <Button size="sm" variant="ghost">选择</Button>
          </div>
        </div>
      </div>
    </Modal>
  </Card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import Card from '@/components/common/Card.vue'
import Button from '@/components/common/Button.vue'
import Modal from '@/components/common/Modal.vue'
import AppIcon from '@/components/icons/AppIcon.vue'
import type { WorkflowDefinition, ChannelConfig } from '@/types'

const props = defineProps<{
  workflow: WorkflowDefinition
  availableChannels: ChannelConfig[]
}>()

const showAddModal = ref(false)

function addChannel(id: string) {
  if (!props.workflow.channels.includes(id)) {
    props.workflow.channels.push(id)
  }
  showAddModal.value = false
}

function removeChannel(index: number) {
  props.workflow.channels.splice(index, 1)
}
</script>
