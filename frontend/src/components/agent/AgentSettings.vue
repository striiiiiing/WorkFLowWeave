<script setup lang="ts">
import { ref, watch } from 'vue'
import { agentsApi, type AgentConfig } from '@/api/agents'
import { useQuery } from '@/composables/useQuery'
import { useAsyncTask } from '@/composables/useAsyncTask'
const emit = defineEmits<{ changed: [] }>()
const query = useQuery((signal) => agentsApi.config(signal))
const action = useAsyncTask()
const toolsAction = useAsyncTask()
const draft = ref<AgentConfig>()
const notice = ref('')
watch(query.data, (value) => {
  if (value) draft.value = structuredClone(value.config)
})
function save() {
  void action.run(async () => {
    if (!draft.value) return
    await agentsApi.updateConfig(draft.value)
    notice.value = '配置已保存，下一轮生效'
    await query.refresh()
    emit('changed')
  })
}
function toggle(plugin: string, enabled: boolean) {
  void toolsAction.run(async () => {
    await agentsApi.updateTool(plugin, enabled)
    await query.refresh()
    emit('changed')
  })
}
</script>
<template>
  <div class="settings">
    <el-alert
      v-if="query.error.value || action.error.value || toolsAction.error.value"
      :title="query.error.value || action.error.value || toolsAction.error.value"
      type="error"
      :closable="false"
    />
    <el-alert v-if="notice" :title="notice" type="success" :closable="false" />
    <p>设置从下一轮生效；当前轮固定模型、工具代次和提示模板。</p>
    <el-form v-if="draft" label-position="top" @submit.prevent="save">
      <el-form-item label="上下文容量（用户预算；留空使用已知模型容量）">
        <el-input-number v-model="draft.context_window" aria-label="上下文容量" :min="1" />
      </el-form-item>
      <el-form-item label="输出预留">
        <el-input-number v-model="draft.output_tokens" aria-label="输出预留" :min="1" />
      </el-form-item>
      <el-form-item label="压缩触发 Token">
        <el-input-number v-model="draft.trigger_tokens" :min="1" />
      </el-form-item>
      <el-form-item label="保留近期 Token">
        <el-input-number v-model="draft.keep_tokens" :min="1" />
      </el-form-item>
      <el-form-item label="摘要 AI 资源（空值复用主模型）">
        <el-select v-model="draft.summary_ai" clearable :value-on-clear="null">
          <el-option
            v-for="ai in [...new Set(query.data.value?.models.map((item) => item.ai))]"
            :key="ai"
            :label="ai"
            :value="ai"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="摘要上下文容量">
        <el-input-number v-model="draft.summary_context_window" :min="1" />
      </el-form-item>
      <el-form-item label="摘要输出上限">
        <el-input-number v-model="draft.summary_max_tokens" :min="1" />
      </el-form-item>
      <el-form-item label="摘要提示模板（每轮固定此版本）">
        <el-input
          v-model="draft.summary_prompt"
          type="textarea"
          :rows="4"
          aria-label="摘要提示模板"
        />
      </el-form-item>
      <el-form-item label="每日 Memory 时区（IANA）">
        <el-input v-model="draft.timezone" aria-label="Memory 时区" />
      </el-form-item>
      <el-form-item label="只读工具并发">
        <el-input-number v-model="draft.read_concurrency" :min="1" />
      </el-form-item>
      <el-form-item label="启用沙箱">
        <el-switch v-model="draft.sandbox.enabled" aria-label="启用沙箱" />
      </el-form-item>
      <el-form-item label="允许沙箱网络">
        <el-switch v-model="draft.sandbox.network" aria-label="允许沙箱网络" />
      </el-form-item>
      <el-button type="primary" native-type="submit" :loading="action.pending.value">
        保存设置
      </el-button>
    </el-form>
    <template v-if="query.data.value">
      <p>
        沙箱：{{
          !query.data.value.sandbox.enabled
            ? '按服务进程权限运行'
            : query.data.value.sandbox.available
              ? '已开启（执行时验证隔离）'
              : '隔离启动失败：bubblewrap 不可用'
        }}
      </p>
      <p>
        并发快照：读 {{ query.data.value.scheduler.reading }}/{{
          query.data.value.scheduler.read_concurrency
        }}
        · 写 {{ query.data.value.scheduler.writing }}/1 · 排队
        {{ query.data.value.scheduler.queued }}
      </p>
      <el-button @click="query.refresh">刷新运行状态</el-button>
      <p>只读路径：{{ query.data.value.readonly_paths.join('、') }}</p>
      <h3>工具插件</h3>
      <p v-if="toolsAction.pending.value">等待当前轮结束后发布工具代次</p>
      <details v-for="tool in query.data.value.tools" :key="tool.plugin + tool.name">
        <summary>
          {{ tool.name }} · {{ tool.execution ?? '未注册' }} · generation {{ tool.generation }} ·
          定义约 {{ tool.definition_tokens }} Tokens
        </summary>
        <el-switch
          :model-value="tool.enabled"
          :disabled="toolsAction.pending.value"
          :aria-label="`切换 ${tool.name}`"
          @change="(value) => toggle(tool.plugin, Boolean(value))"
        />
        <p>{{ tool.description }}</p>
        <pre>{{
          tool.input_schema
            ? JSON.stringify(tool.input_schema, null, 2)
            : '插件未注册，Schema 不可用'
        }}</pre>
      </details>
    </template>
  </div>
</template>
<style scoped>
.settings {
  display: grid;
  gap: 12px;
  overflow-wrap: anywhere;
}
pre {
  white-space: pre-wrap;
  font-size: 12px;
}
details {
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
summary {
  cursor: pointer;
}
</style>
