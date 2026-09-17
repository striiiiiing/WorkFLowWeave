<template>
  <!-- [Design Decision DEC-LAYOUT-01] 垂直流式阶梯编排卡片：数据采集阶段 -->
  <Card
    title="阶段 1：数据采集与共享输入编排 (Collection)"
    subtitle="配置输入采集源、排列顺序、错误策略及调用级参数覆写"
    icon="database"
  >
    <div class="space-y-4">
      <!-- 策略配置 -->
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 p-3 bg-slate-50 dark:bg-slate-900/50 rounded-lg border border-slate-200/60 dark:border-slate-700/60">
        <div>
          <label class="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
            单个来源错误策略 (on_error)
          </label>
          <select
            v-model="workflow.on_error"
            class="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 min-h-[44px]"
          >
            <option value="stop">stop (遇到来源错误立即终止)</option>
            <option value="skip">skip (跳过失败来源并继续)</option>
          </select>
        </div>

        <div>
          <label class="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
            全部来源无内容策略 (on_all_empty)
          </label>
          <select
            v-model="workflow.on_all_empty"
            class="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 min-h-[44px]"
          >
            <option value="skip">skip (全空时正常跳过，不发起后续分析)</option>
            <option value="stop">stop (全空时标记为任务失败)</option>
          </select>
        </div>
      </div>

      <!-- 已选采集源列表 -->
      <div>
        <div class="flex items-center justify-between mb-2">
          <span class="text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider">
            所选采集源 (按顺序编排共享输入)
          </span>
          <Button size="sm" variant="secondary" icon="plus" @click="showAddModal = true">
            添加采集源
          </Button>
        </div>

        <div v-if="workflow.sources.length === 0" class="p-6 text-center border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-lg text-slate-400 text-sm">
          暂未选择采集源，请点击上方按钮添加
        </div>

        <div v-else class="space-y-2">
          <div
            v-for="(sourceId, index) in workflow.sources"
            :key="sourceId"
            class="flex items-center justify-between p-3 bg-white dark:bg-slate-800/80 rounded-lg border border-slate-200 dark:border-slate-700"
          >
            <div class="flex items-center gap-3">
              <span class="w-6 h-6 rounded-full bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 text-xs font-bold flex items-center justify-center">
                {{ index + 1 }}
              </span>
              <div>
                <span class="font-mono text-sm font-semibold text-slate-900 dark:text-slate-100">{{ sourceId }}</span>
                <span class="ml-2 text-xs text-slate-400">已就绪</span>
              </div>
            </div>

            <!-- 操作按钮：排序与移除 -->
            <div class="flex items-center gap-1">
              <button
                type="button"
                :disabled="index === 0"
                class="p-2 text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 disabled:opacity-30 min-h-[44px] min-w-[44px] flex items-center justify-center"
                title="上移"
                @click="moveSource(index, -1)"
              >
                <AppIcon name="chevron-up" size="sm" />
              </button>
              <button
                type="button"
                :disabled="index === workflow.sources.length - 1"
                class="p-2 text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 disabled:opacity-30 min-h-[44px] min-w-[44px] flex items-center justify-center"
                title="下移"
                @click="moveSource(index, 1)"
              >
                <AppIcon name="chevron-down" size="sm" />
              </button>
              <button
                type="button"
                class="p-2 text-red-500 hover:text-red-700 min-h-[44px] min-w-[44px] flex items-center justify-center"
                title="移除"
                @click="removeSource(index)"
              >
                <AppIcon name="trash" size="sm" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 添加来源弹窗 -->
    <Modal v-model="showAddModal" title="添加数据采集源">
      <div class="space-y-3">
        <p class="text-xs text-slate-500">选择要引入此工作流的已配置采集源：</p>
        <div class="max-h-60 overflow-y-auto space-y-1">
          <div
            v-for="src in availableSources"
            :key="src.id"
            class="flex items-center justify-between p-2.5 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700/50 cursor-pointer"
            @click="addSource(src.id)"
          >
            <div>
              <p class="font-mono text-sm font-medium">{{ src.id }}</p>
              <p class="text-xs text-slate-400">插件: {{ src.collector }}</p>
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
import type { WorkflowDefinition, SourceConfig } from '@/types'

const props = defineProps<{
  workflow: WorkflowDefinition
  availableSources: SourceConfig[]
}>()

const showAddModal = ref(false)

function addSource(id: string) {
  if (!props.workflow.sources.includes(id)) {
    props.workflow.sources.push(id)
  }
  showAddModal.value = false
}

function removeSource(index: number) {
  props.workflow.sources.splice(index, 1)
}

function moveSource(index: number, direction: number) {
  const targetIndex = index + direction
  if (targetIndex < 0 || targetIndex >= props.workflow.sources.length) return
  const item = props.workflow.sources[index]
  props.workflow.sources.splice(index, 1)
  props.workflow.sources.splice(targetIndex, 0, item)
}
</script>
