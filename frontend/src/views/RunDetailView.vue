<template>
  <div class="max-w-4xl mx-auto space-y-6 pb-12">
    <!-- 顶部状态栏 -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 sticky top-0 z-20 bg-slate-50/90 dark:bg-slate-900/90 backdrop-blur py-3 border-b border-slate-200 dark:border-slate-800">
      <div>
        <div class="flex items-center gap-2">
          <router-link to="/runs" class="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 text-sm">
            运行记录
          </router-link>
          <span class="text-slate-300">/</span>
          <span class="font-mono font-bold text-base text-slate-900 dark:text-slate-100">{{ sessionId }}</span>
        </div>
        <p class="text-xs text-slate-400 mt-0.5">
          所属工作流: <strong class="font-mono text-slate-600 dark:text-slate-300">{{ session?.workflow_id }}</strong>
        </p>
      </div>

      <div class="flex items-center gap-2">
        <Button variant="secondary" icon="rotate-ccw" @click="loadDetail">
          刷新
        </Button>

        <!-- 活动状态可取消 -->
        <Button
          v-if="session?.status === 'running' || session?.status === 'created'"
          variant="danger"
          icon="stop"
          @click="handleCancel"
        >
          取消执行
        </Button>

        <!-- 失败或中断可恢复 -->
        <Button
          v-if="session?.status === 'failed' || session?.status === 'interrupted'"
          variant="primary"
          icon="rotate-ccw"
          @click="handleRecover"
        >
          从断点恢复 (Recover)
        </Button>
      </div>
    </div>

    <!-- 加载中 -->
    <div v-if="loading && !session" class="p-12 text-center text-slate-400">
      <AppIcon name="loader" :spin="true" class="mx-auto mb-2" size="lg" />
      <span>加载 Session 详情中...</span>
    </div>

    <!-- 概览卡片 -->
    <Card v-else-if="session" title="执行概览与元数据">
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
        <div>
          <span class="text-slate-400">运行状态</span>
          <div class="mt-1">
            <Badge :status="session.status" />
          </div>
        </div>

        <div>
          <span class="text-slate-400">当前阶段</span>
          <p class="font-semibold text-slate-800 dark:text-slate-200 mt-1 uppercase">
            {{ session.current_stage }}
          </p>
        </div>

        <div>
          <span class="text-slate-400">业务版本</span>
          <p class="font-mono font-bold text-slate-800 dark:text-slate-200 mt-1">
            v{{ session.version }}
          </p>
        </div>

        <div>
          <span class="text-slate-400">快照可用性</span>
          <p class="font-semibold text-slate-800 dark:text-slate-200 mt-1">
            {{ session.snapshot_availability }}
          </p>
        </div>
      </div>

      <!-- 错误信息横幅 (如有) -->
      <div v-if="session.error" class="mt-4 p-3 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-lg">
        <p class="text-xs font-bold text-red-800 dark:text-red-200 flex items-center gap-1.5">
          <AppIcon name="alert-triangle" size="sm" />
          执行异常: {{ session.error.code }}
        </p>
        <p class="text-xs text-red-700 dark:text-red-300 mt-1 font-mono">
          {{ session.error.message }}
        </p>
      </div>
    </Card>

    <!-- [Design Decision DEC-LAYOUT-01] 阶段流式正文卡片列表 -->
    <div v-if="session" class="space-y-4">
      <h3 class="text-sm font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider">
        阶段产物与执行进度
      </h3>

      <!-- 阶段 1: 数据采集共享输入 -->
      <Card title="1. 数据采集与共享输入 (Collection Stage)" icon="database">
        <div class="flex items-center justify-between text-xs">
          <div>
            <span class="text-slate-400">产物可用性:</span>
            <span class="ml-2 font-mono font-semibold">
              {{ session.stage_artifacts?.collection?.availability || '未知' }}
            </span>
          </div>
          <Button
            size="sm"
            variant="secondary"
            @click="viewPhaseContent('collection')"
          >
            查看共享输入正文
          </Button>
        </div>
      </Card>

      <!-- 阶段 2: Fan-Out 分析分支 -->
      <Card title="2. 并行 AI 分析分支 (Analysis Stage)" icon="bot">
        <div class="flex items-center justify-between text-xs">
          <div>
            <span class="text-slate-400">产物可用性:</span>
            <span class="ml-2 font-mono font-semibold">
              {{ session.stage_artifacts?.analysis?.availability || '未知' }}
            </span>
          </div>
          <Button
            size="sm"
            variant="secondary"
            @click="viewPhaseContent('analysis')"
          >
            查看分支分析结果
          </Button>
        </div>
      </Card>

      <!-- 阶段 3: Fan-In 汇聚总结 -->
      <Card title="3. 汇聚汇总产物 (Fan-In Aggregate Stage)" icon="workflow">
        <div class="flex items-center justify-between text-xs">
          <div>
            <span class="text-slate-400">产物可用性:</span>
            <span class="ml-2 font-mono font-semibold">
              {{ session.stage_artifacts?.fan_in?.availability || '未启用或未产出' }}
            </span>
          </div>
          <Button
            size="sm"
            variant="secondary"
            @click="viewPhaseContent('fan_in')"
          >
            查看汇总正文
          </Button>
        </div>
      </Card>

      <!-- 阶段 4: 通知渠道回执 -->
      <Card title="4. 通知与投递回执 (Notification Stage)" icon="mail">
        <div class="flex items-center justify-between text-xs">
          <div>
            <span class="text-slate-400">产物可用性:</span>
            <span class="ml-2 font-mono font-semibold">
              {{ session.stage_artifacts?.notification?.availability || '未配置或执行中' }}
            </span>
          </div>
          <Button
            size="sm"
            variant="secondary"
            @click="viewPhaseContent('notification')"
          >
            查看投递回执
          </Button>
        </div>
      </Card>
    </div>

    <!-- 阶段正文查看模态弹窗 -->
    <Modal
      v-model="modalOpen"
      :title="`阶段正文查看 - ${activeStage}`"
      max-width="2xl"
    >
      <div v-if="modalLoading" class="p-8 text-center text-slate-400">
        <AppIcon name="loader" :spin="true" class="mx-auto mb-2" size="lg" />
        <span>正在读取业务存档正文...</span>
      </div>

      <div v-else class="space-y-3">
        <div class="flex items-center justify-between">
          <span class="text-xs text-slate-400">
            业务版本: v{{ session?.version }} (只读不可篡改)
          </span>
          <Button size="sm" variant="ghost" icon="copy" @click="copyContent">
            复制文本
          </Button>
        </div>

        <pre class="p-4 bg-slate-900 text-slate-100 rounded-lg text-xs font-mono overflow-x-auto max-h-96 selection:bg-blue-600">{{ modalContentText }}</pre>
      </div>
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import Card from '@/components/common/Card.vue'
import Button from '@/components/common/Button.vue'
import Badge from '@/components/common/Badge.vue'
import Modal from '@/components/common/Modal.vue'
import AppIcon from '@/components/icons/AppIcon.vue'
import { useRunStore } from '@/stores/runStore'
import type { StageName } from '@/types'

const route = useRoute()
const runStore = useRunStore()

const sessionId = computed(() => String(route.params.id))
const session = computed(() => runStore.activeSession)
const loading = ref(false)

const modalOpen = ref(false)
const modalLoading = ref(false)
const activeStage = ref<StageName>('collection')
const activeContent = ref<any>(null)

const modalContentText = computed(() => {
  if (activeContent.value === null || activeContent.value === undefined) {
    return '暂无可用正文或正文未启用持久化备份'
  }
  if (typeof activeContent.value === 'string') {
    return activeContent.value
  }
  return JSON.stringify(activeContent.value, null, 2)
})

async function loadDetail() {
  loading.value = true
  try {
    const detail = await runStore.fetchSessionDetail(sessionId.value)
    if (detail.status === 'running' || detail.status === 'created') {
      runStore.startPolling(sessionId.value)
    }
  } catch (err: any) {
    alert(`加载失败: ${err.message}`)
  } finally {
    loading.value = false
  }
}

async function viewPhaseContent(stage: StageName) {
  if (!session.value) return
  activeStage.value = stage
  modalOpen.value = true
  modalLoading.value = true
  try {
    const res = await runStore.fetchPhaseContent(
      sessionId.value,
      stage,
      session.value.version
    )
    activeContent.value = res.content
  } catch (err: any) {
    activeContent.value = `读取失败: ${err.message}`
  } finally {
    modalLoading.value = false
  }
}

async function handleCancel() {
  if (confirm('确认取消当前运行？')) {
    await runStore.cancelRun(sessionId.value)
    await loadDetail()
  }
}

async function handleRecover() {
  if (confirm('确认从原有断点 checkpoint 恢复执行？')) {
    const newSessionId = await runStore.recoverRun(sessionId.value)
    alert(`已提交恢复任务，Session ID: ${newSessionId}`)
    await loadDetail()
  }
}

function copyContent() {
  navigator.clipboard.writeText(modalContentText.value)
  alert('内容已复制到剪贴板')
}

onMounted(() => {
  loadDetail()
})

onUnmounted(() => {
  runStore.stopPolling()
})
</script>
