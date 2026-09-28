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
  RunProgress,
  stages,
} from '@/modules/runs/public'
import PageHeader from '@/shared/ui/PageHeader.vue'
import SectionCard from '@/shared/ui/SectionCard.vue'
const route = useRoute()
const router = useRouter()
const id = computed(() => String(route.params.id))
const detail = useRunDetail(id)
const {
  session: query,
  active,
  recovery,
  stageRecovery,
  selectedStage,
  stageRecoveryEnabled,
  phases,
  actionError,
  actionPending,
  refreshAll,
} = detail
const { data: session, pending, error } = query
const advanced = ref(false)
const restartOpen = ref(false)
const observed = computed(() => ['connected', 'closed'].includes(query.connection.value))
async function cancel() {
  const result = await detail.cancel()
  if (result.status === 'success') ElMessage.info('已接受取消请求')
}
async function recover() {
  const result = await detail.resume()
  if (result.status === 'success' && result.value.session_id !== id.value)
    await router.push({ name: 'run-detail', params: { id: result.value.session_id } })
}
async function restart() {
  const result = await detail.resume({ stage: selectedStage.value })
  if (result.status === 'success') {
    restartOpen.value = false
    ElMessage.info('已接受阶段重新执行请求')
  }
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
          observed &&
          ['interrupted', 'cancelled'].includes(session.status)
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
      <el-button
        v-if="session"
        :disabled="active || actionPending || !observed"
        @click="restartOpen = true"
      >
        从阶段重新执行
      </el-button>
    </PageHeader>
    <el-alert
      v-if="error || actionError"
      :title="error || actionError"
      type="error"
      :closable="false"
      show-icon
    />
    <el-alert
      v-if="query.connectionError.value"
      :title="query.connectionError.value"
      type="warning"
      :closable="false"
      show-icon
    >
      <el-button size="small" :loading="pending" @click="refreshAll">重新同步</el-button>
    </el-alert>
    <p
      v-else-if="query.connection.value === 'connecting' || query.connection.value === 'syncing'"
      class="muted text-sm"
      role="status"
    >
      {{ query.connection.value === 'connecting' ? '正在连接进度订阅…' : '正在同步运行状态…' }}
    </p>
    <el-skeleton v-if="pending && !session" :rows="6" />
    <template v-if="session">
      <SectionCard title="本次运行">
        <template #actions>
          <span class="muted text-xs">
            {{
              query.connection.value === 'connected'
                ? '进度已连接'
                : query.connection.value === 'closed'
                  ? '终态已核对'
                  : '进度待同步'
            }}
          </span>
          <el-switch v-model="advanced" active-text="高级模式" aria-label="高级模式" />
        </template>
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
      <section class="run-section" aria-labelledby="progress-title">
        <h2 id="progress-title" class="font-semibold mb-4">执行进度</h2>
        <RunProgress :session="session" :active="active" />
      </section>
      <section class="run-section" aria-labelledby="report-title">
        <h2 id="report-title" class="font-semibold mb-4">最终报告</h2>
        <p
          v-if="
            !phases.aggregate.data.value &&
            !phases.aggregate.pending.value &&
            !phases.aggregate.error.value
          "
          class="muted"
        >
          {{ active ? '最终报告尚未生成。' : '本次运行没有最终报告记录。' }}
        </p>
        <PhaseReport :report="phases.aggregate" :active="active" :advanced="advanced" />
      </section>
      <section class="run-section" aria-labelledby="process-title">
        <h2 id="process-title" class="font-semibold mb-4">过程正文</h2>
        <RunProcessDetails :phases="phases" :active="active" :advanced="advanced" />
      </section>
      <SectionCard v-if="advanced" title="运行技术信息">
        <dl class="space-y-2 text-sm break-all">
          <div>
            <dt class="muted">执行轮次</dt>
            <dd>{{ session.execution_epoch }}</dd>
          </div>
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
    <el-dialog
      v-model="restartOpen"
      title="从阶段重新执行"
      width="min(480px, 92vw)"
      @open="stageRecoveryEnabled = true"
      @close="stageRecoveryEnabled = false"
    >
      <el-select v-model="selectedStage" aria-label="重新执行起始阶段" class="w-full">
        <el-option
          v-for="stage in stages.filter((item) => item.key !== 'finish')"
          :key="stage.key"
          :value="stage.key"
          :label="stage.label"
        />
        <el-option value="process" label="重新处理原始采集结果" />
      </el-select>
      <p class="mt-4 text-sm">
        {{
          selectedStage === 'process'
            ? '使用已保存的原始采集结果重新处理，不重新采集；进入通知阶段会重新发送。'
            : '重做所选阶段及后续流程；进入通知阶段会重新发送。'
        }}
      </p>
      <el-alert
        v-if="stageRecovery.data.value && !stageRecovery.data.value.available"
        class="mt-4"
        :title="stageRecovery.data.value.reason?.message ?? '此阶段暂不可重新执行'"
        type="warning"
        :closable="false"
      />
      <p v-if="stageRecovery.error.value" class="mt-4 text-red-700" role="alert">
        {{ stageRecovery.error.value }}
      </p>
      <template #footer>
        <el-button @click="restartOpen = false">取消</el-button>
        <el-button v-if="stageRecovery.error.value" @click="stageRecovery.refresh">
          重新检查
        </el-button>
        <el-button
          type="primary"
          :loading="actionPending || stageRecovery.pending.value"
          :disabled="active || !observed || !stageRecovery.data.value?.available"
          @click="restart"
        >
          重新执行
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>
<style scoped>
.run-section {
  padding-top: 24px;
  border-top: 1px solid var(--el-border-color-lighter);
  min-width: 0;
}
</style>
