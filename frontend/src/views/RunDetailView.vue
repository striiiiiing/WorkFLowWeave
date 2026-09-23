<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { runsApi } from '@/api/runs'
import { useSession } from '@/composables/useSession'
import { useQuery } from '@/composables/useQuery'
import { useAsyncTask } from '@/composables/useAsyncTask'
import {
  availabilityLabels,
  stages,
  sessionStates,
  formatWorkflowName,
  formatTime,
} from '@/domain/session'
import PageHeader from '@/components/common/PageHeader.vue'
import SectionCard from '@/components/common/SectionCard.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import PhaseReport from '@/components/report/PhaseReport.vue'
import AgentContinueButton from '@/components/agent/AgentContinueButton.vue'
const route = useRoute()
const router = useRouter()
const id = computed(() => String(route.params.id))
const { data: session, pending, error, refresh } = useSession(id)
const action = useAsyncTask()
const advanced = ref(false)
const active = computed(() => (session.value ? sessionStates[session.value.status].active : false))
const recovery = useQuery(
  async (signal) => {
    if (!session.value || active.value) return undefined
    return runsApi.recovery(id.value, signal)
  },
  [id, () => session.value?.version],
)
const stageName = computed(
  () => stages.find((stage) => stage.key === session.value?.stage)?.label ?? '尚未开始',
)
async function refreshAll() {
  await refresh()
  await recovery.refresh()
}
function cancel() {
  void action.run(async () => {
    const result = await runsApi.cancel(id.value)
    ElMessage.info(result.cancelled ? '已接受取消请求' : '当前运行未被取消，请查看最新状态')
    await refreshAll()
  })
}
function recover() {
  void action.run(async () => {
    try {
      const result = await runsApi.recover(id.value)
      if (result.session_id === id.value) await refresh()
      else await router.push(`/runs/${result.session_id}`)
    } finally {
      await recovery.refresh()
    }
  })
}
</script>
<template>
  <div class="max-w-5xl mx-auto space-y-6">
    <PageHeader
      :title="session ? formatWorkflowName(session.workflow_name) : '运行报告'"
      description="查看本次运行的结果与执行情况"
    >
      <el-button :loading="pending" @click="refreshAll">刷新</el-button>
      <AgentContinueButton v-if="session && ['completed', 'partial'].includes(session.status)" :workflow-session-id="id" />
      <el-popconfirm v-if="active" title="确认取消执行？" @confirm="cancel">
        <template #reference>
          <el-button type="danger" :disabled="action.pending.value">取消执行</el-button>
        </template>
      </el-popconfirm>
      <el-button
        v-if="
          recovery.data.value?.available &&
          session &&
          ['failed', 'interrupted', 'cancelled', 'partial'].includes(session.status)
        "
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
      <SectionCard title="本次运行">
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-5 text-sm">
          <div>
            <p class="muted mb-2">运行状态</p>
            <StatusBadge :status="session.status" />
          </div>
          <div>
            <p class="muted mb-2">当前阶段</p>
            {{ stageName }}
          </div>
          <div>
            <p class="muted mb-2">开始时间</p>
            {{ formatTime(session.created_at) }}
          </div>
          <div>
            <p class="muted mb-2">结束时间</p>
            {{ session.finished_at ? formatTime(session.finished_at) : '尚未结束' }}
          </div>
        </div>
        <el-alert
          v-if="session.error"
          :title="session.error.message"
          type="error"
          :closable="false"
          class="mt-5"
        />
        <p
          v-if="
            recovery.data.value &&
            !recovery.data.value.available &&
            ['failed', 'interrupted', 'cancelled', 'partial'].includes(session.status)
          "
          class="mt-4 text-amber-800"
        >
          暂时不能恢复：{{ recovery.data.value.reason?.message }}
        </p>
        <div v-if="recovery.error.value" class="mt-3" role="alert">
          无法检查恢复条件：{{ recovery.error.value }}
          <el-button size="small" @click="recovery.refresh">重新检查</el-button>
        </div>
      </SectionCard>
      <div class="flex justify-end">
        <el-switch v-model="advanced" active-text="高级模式" aria-label="高级模式" />
      </div>
      <SectionCard title="最终报告" description="本次运行生成的分析结果">
        <PhaseReport
          :id="id"
          :version="session.version"
          stage="aggregate"
          :active="active"
          :advanced="advanced"
        />
      </SectionCard>
      <SectionCard title="通知状态" description="每份报告在各个渠道的投递情况">
        <PhaseReport
          :id="id"
          :version="session.version"
          stage="notify"
          :active="active"
          :advanced="advanced"
        />
      </SectionCard>
      <SectionCard title="过程详情" description="需要追溯结果时，可展开查看采集和分析过程">
        <details
          v-for="stage in stages.filter((item) =>
            ['collect', 'analyze', 'finish'].includes(item.key),
          )"
          :key="stage.key"
          class="border-b last:border-0"
        >
          <summary class="report-disclosure font-medium">{{ stage.label }}</summary>
          <PhaseReport
            class="pb-3"
            :id="id"
            :version="session.version"
            :stage="stage.key"
            :active="active"
            :advanced="advanced"
          />
        </details>
      </SectionCard>
      <SectionCard v-if="advanced" title="运行技术信息">
        <dl class="space-y-2 text-sm break-all">
          <div>
            <dt class="muted">运行编号</dt>
            <dd>{{ session.session_id }}</dd>
          </div>
          <div>
            <dt class="muted">工作流编号</dt>
            <dd>{{ session.workflow_id }}</dd>
          </div>
          <div>
            <dt class="muted">记录版本</dt>
            <dd>{{ session.version }}</dd>
          </div>
          <div>
            <dt class="muted">原始配置</dt>
            <dd>{{ availabilityLabels[session.snapshot_availability] }}</dd>
          </div>
          <div v-if="session.error">
            <dt class="muted">错误代码</dt>
            <dd>{{ session.error.code }}</dd>
          </div>
        </dl>
      </SectionCard>
    </template>
  </div>
</template>
