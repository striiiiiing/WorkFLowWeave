<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance } from 'element-plus'
import { resourcesApi } from '@/api/resources'
import { createWorkflow } from '@/domain/workflow'
import { idRule } from '@/domain/forms'
import { useQuery } from '@/composables/useQuery'
import { useAsyncTask } from '@/composables/useAsyncTask'
import PageHeader from '@/components/common/PageHeader.vue'
import SectionCard from '@/components/common/SectionCard.vue'
import SourceStepCard from '@/components/workflow/SourceStepCard.vue'
import FanOutTaskCard from '@/components/workflow/FanOutTaskCard.vue'
import FanInCard from '@/components/workflow/FanInCard.vue'
import NotificationCard from '@/components/workflow/NotificationCard.vue'
import BackupMatrix from '@/components/workflow/BackupMatrix.vue'
const route = useRoute()
const router = useRouter()
const id = computed(() => (route.params.id ? String(route.params.id) : undefined))
const workflow = ref(createWorkflow())
const form = ref<FormInstance>()
const save = useAsyncTask()
const advanced = ref(false)
const {
  data: configs,
  pending: modelsPending,
  error: modelsError,
  refresh: refreshModels,
} = useQuery((signal) => resourcesApi.list('ai', signal))
const { data, pending, error, refresh } = useQuery(
  async (signal) => {
    const [sources, channels, existing] = await Promise.all([
      resourcesApi.list('sources', signal),
      resourcesApi.list('channels', signal),
      id.value
        ? resourcesApi.get('workflows', id.value, signal)
        : Promise.resolve(createWorkflow()),
    ])
    return { sources, channels, existing }
  },
  [id],
)
watch(data, (value) => {
  if (value) workflow.value = structuredClone(value.existing)
})
function submit() {
  if (!form.value) return
  const editorForm = form.value
  void save.run(async () => {
    if (!(await editorForm.validate(() => {}))) return
    if (!workflow.value.id) workflow.value.id = crypto.randomUUID()
    if (id.value) await resourcesApi.replace('workflows', id.value, workflow.value)
    else await resourcesApi.create('workflows', workflow.value)
    ElMessage.success('工作流已保存')
    await router.push('/workflows')
  })
}
</script>
<template>
  <div class="max-w-4xl mx-auto pb-10">
    <PageHeader
      :title="id ? '编辑工作流' : '新建工作流'"
      description="按步骤配置采集、分析、汇聚与分发"
    >
      <router-link to="/workflows"><el-button>取消</el-button></router-link>
      <el-button
        type="primary"
        :loading="save.pending.value"
        :disabled="!data || !configs || modelsPending || !!modelsError"
        @click="submit"
      >
        保存工作流
      </el-button>
    </PageHeader>
    <el-alert
      v-if="error || modelsError || save.error.value"
      :title="error || modelsError || save.error.value"
      type="error"
      :closable="false"
      show-icon
    />
    <el-button v-if="error" @click="refresh">重新加载</el-button>
    <el-button v-if="modelsError" @click="refreshModels">重新加载模型列表</el-button>
    <el-skeleton v-if="pending || (!configs && modelsPending)" :rows="10" animated />
    <el-form
      novalidate
      v-if="data && configs"
      ref="form"
      :model="workflow"
      label-position="top"
      @submit.prevent="submit"
    >
      <el-form-item label="高级模式"><el-switch v-model="advanced" /></el-form-item>
      <div class="flow-stack">
        <SectionCard title="基本信息与运行策略">
          <div class="form-grid">
            <el-form-item
              label="工作流 ID（留空自动生成）"
              prop="id"
              :rules="{ ...idRule, required: false }"
            >
              <el-input v-model="workflow.id" placeholder="nightly_analysis" />
            </el-form-item>
            <el-form-item label="显示名称">
              <el-input v-model="workflow.name" placeholder="夜间日志分析" />
            </el-form-item>
            <el-form-item label="启用工作流"><el-switch v-model="workflow.enabled" /></el-form-item>
            <el-form-item label="定时间隔 / 秒（留空只手动运行）">
              <el-input-number
                :model-value="workflow.interval_seconds ?? undefined"
                :min="0.001"
                @update:model-value="workflow.interval_seconds = $event ?? null"
              />
            </el-form-item>
          </div>
        </SectionCard>
        <SourceStepCard v-model="workflow" :sources="data.sources" :advanced="advanced" />
        <FanOutTaskCard
          v-model="workflow"
          :configs="configs"
          :models-pending="modelsPending"
          :advanced="advanced"
          @refresh-models="refreshModels"
        />
        <FanInCard v-model="workflow" :configs="configs" :advanced="advanced" />
        <NotificationCard v-model="workflow" :channels="data.channels" :advanced="advanced" />
        <BackupMatrix v-if="advanced" v-model="workflow.backup" />
      </div>
    </el-form>
  </div>
</template>
