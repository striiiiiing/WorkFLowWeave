<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { runsApi } from '@/api/runs'
import { useSession } from '@/composables/useSession'
import { useQuery } from '@/composables/useQuery'
import { useAsyncTask } from '@/composables/useAsyncTask'
import { availabilityLabels, stages, sessionStates, formatWorkflowName } from '@/domain/session'
import type { WorkflowStage } from '@/types'
import PageHeader from '@/components/common/PageHeader.vue'
import SectionCard from '@/components/common/SectionCard.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
const route = useRoute()
const router = useRouter()
const id = computed(() => String(route.params.id))
const { data: session, pending, error, refresh } = useSession(id)
const action = useAsyncTask()
const phaseRows = computed(() =>
  stages.map((stage) => ({
    ...stage,
    availability: session.value?.artifacts.find((item) => item.stage === stage.key)?.availability,
  })),
)
const selected = ref<{ stage: WorkflowStage; version: number }>()
const modal = ref(false)
const phase = useQuery(
  async (signal) =>
    selected.value
      ? runsApi.phase(id.value, selected.value.stage, selected.value.version, signal)
      : undefined,
  [selected],
)
const content = computed(() =>
  typeof phase.data.value?.content === 'string'
    ? phase.data.value.content
    : JSON.stringify(phase.data.value?.content, null, 2),
)
function openPhase(stage: WorkflowStage) {
  if (!session.value) return
  selected.value = { stage, version: session.value.version }
  modal.value = true
}
function cancel() {
  void action.run(async () => {
    const result = await runsApi.cancel(id.value)
    ElMessage.info(result.cancelled ? '已接受取消请求' : '当前运行未被取消，请查看最新状态')
    await refresh()
  })
}
function recover() {
  void action.run(async () => {
    const result = await runsApi.recover(id.value)
    if (result.session_id === id.value) await refresh()
    else await router.push(`/runs/${result.session_id}`)
  })
}
function copy() {
  void action.run(async () => {
    await navigator.clipboard.writeText(content.value ?? '')
    ElMessage.success('已复制')
  })
}
</script>
<template>
  <div class="max-w-5xl mx-auto space-y-6">
    <PageHeader
      :title="id"
      :description="
        session
          ? `所属工作流：${formatWorkflowName(session.workflow_name)}（${session.workflow_id}）`
          : '运行详情'
      "
    >
      <el-button :loading="pending" @click="refresh">刷新</el-button>
      <el-popconfirm
        v-if="session && sessionStates[session.status].active"
        title="确认取消执行？"
        @confirm="cancel"
      >
        <template #reference>
          <el-button type="danger" :disabled="action.pending.value">取消执行</el-button>
        </template>
      </el-popconfirm>
      <el-button
        v-if="session && ['failed', 'interrupted'].includes(session.status)"
        type="primary"
        :loading="action.pending.value"
        @click="recover"
      >
        恢复执行
      </el-button>
    </PageHeader>
    <el-alert
      v-if="error || action.error.value"
      :title="error || action.error.value"
      type="error"
      :closable="false"
      show-icon
    />
    <el-skeleton v-if="pending && !session" :rows="6" animated />
    <template v-if="session">
      <SectionCard title="执行概览与元数据">
        <div class="grid grid-cols-2 md:grid-cols-4 gap-5">
          <div>
            <p class="muted mb-2">运行状态</p>
            <StatusBadge :status="session.status" />
          </div>
          <div>
            <p class="muted mb-2">当前阶段</p>
            {{ session.stage ?? '尚未开始' }}
          </div>
          <div>
            <p class="muted mb-2">业务版本</p>
            v{{ session.version }}
          </div>
          <div>
            <p class="muted mb-2">快照可用性</p>
            {{ availabilityLabels[session.snapshot_availability] }}
          </div>
        </div>
        <el-alert
          v-if="session.error"
          :title="session.error.message"
          :description="session.error.code"
          type="error"
          :closable="false"
          class="mt-5"
        />
      </SectionCard>
      <SectionCard title="阶段执行流程与只读产物">
        <el-timeline>
          <el-timeline-item
            v-for="stage in phaseRows"
            :key="stage.key"
            :type="session.stage === stage.key ? 'primary' : 'info'"
          >
            <div class="flex items-center justify-between gap-3">
              <div>
                <h3 class="font-semibold">{{ stage.label }}</h3>
                <p class="muted text-xs mt-2">
                  {{ stage.availability ? availabilityLabels[stage.availability] : '无产物记录' }}
                </p>
              </div>
              <el-button size="small" @click="openPhase(stage.key)">查看正文</el-button>
            </div>
          </el-timeline-item>
        </el-timeline>
      </SectionCard>
    </template>
    <el-dialog
      v-model="modal"
      :title="`阶段正文 · ${selected?.stage ?? ''}`"
      width="760px"
      @closed="selected = undefined"
    >
      <el-alert
        v-if="phase.error.value"
        :title="phase.error.value"
        type="error"
        :closable="false"
      />
      <el-skeleton v-if="phase.pending.value" :rows="4" animated />
      <template v-else-if="phase.data.value">
        <div class="flex items-center justify-between mb-4">
          <span class="muted">
            业务版本 v{{ phase.data.value.version }} ·
            {{ availabilityLabels[phase.data.value.availability] }}
          </span>
          <el-button v-if="phase.data.value.availability === 'available'" @click="copy">
            复制
          </el-button>
        </div>
        <el-alert
          v-if="phase.data.value.error"
          :title="phase.data.value.error.message"
          type="error"
          :closable="false"
        />
        <pre
          v-if="phase.data.value.availability === 'available'"
          class="bg-slate-900 text-slate-100 p-4 rounded-lg max-h-96 overflow-auto text-xs"
          >{{ content }}</pre>
      </template>
    </el-dialog>
  </div>
</template>
