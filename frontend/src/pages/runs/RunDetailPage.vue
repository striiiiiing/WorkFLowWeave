<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import ContinueInAgent from '@/pages/integrations/ContinueInAgent.vue'
import {
  useRunDetail,
  availabilityLabels,
  formatWorkflowName,
  PhaseReport,
  RunSummary,
  RunActions,
  RunProcessDetails,
} from '@/modules/runs/public'
import PageHeader from '@/shared/ui/PageHeader.vue'
import SectionCard from '@/shared/ui/SectionCard.vue'
const route = useRoute()
const router = useRouter()
const id = computed(() => String(route.params.id))
const detail = useRunDetail(id)
const { session: query, active, recovery, phases, actionError, actionPending, refreshAll } = detail
const { data: session, pending, error } = query
const advanced = ref(false)
async function cancel() {
  const result = await detail.cancel()
  if (result.status === 'success') ElMessage.info('已接受取消请求')
}
async function recover() {
  const result = await detail.recover()
  if (result.status === 'success' && result.value.session_id !== id.value)
    await router.push({ name: 'run-detail', params: { id: result.value.session_id } })
}
</script>
<template>
  <div class="max-w-5xl mx-auto space-y-6">
    <PageHeader
      :title="session ? formatWorkflowName(session.workflow_name) : '运行报告'"
      description="查看本次运行的结果与执行情况"
    >
      <RunActions
        :pending="pending"
        :active="active"
        :action-pending="actionPending"
        :can-recover="
          !!recovery.data.value?.available &&
          !!session &&
          ['failed', 'interrupted', 'cancelled', 'partial'].includes(session.status)
        "
        :can-continue="!!session && ['completed', 'partial'].includes(session.status)"
        @refresh="refreshAll"
        @cancel="cancel"
        @recover="recover"
      >
        <template #continuation>
          <ContinueInAgent v-if="session" :session="session" />
        </template>
      </RunActions>
    </PageHeader>
    <el-alert
      v-if="error || actionError"
      :title="error || actionError"
      type="error"
      :closable="false"
      show-icon
    />
    <el-skeleton v-if="pending && !session" :rows="6" animated />
    <template v-if="session">
      <SectionCard title="本次运行">
        <RunSummary :session="session" />
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
        <PhaseReport :report="phases.aggregate" :active="active" :advanced="advanced" />
      </SectionCard>
      <SectionCard title="通知状态" description="每份报告在各个渠道的投递情况">
        <PhaseReport :report="phases.notify" :active="active" :advanced="advanced" />
      </SectionCard>
      <SectionCard title="过程详情" description="需要追溯结果时，可展开查看采集和分析过程">
        <RunProcessDetails :phases="phases" :active="active" :advanced="advanced" />
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
