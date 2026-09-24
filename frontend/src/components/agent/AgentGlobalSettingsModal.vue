<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { agentsApi, type AgentConfig } from '@/api/agents'
import { useQuery } from '@/shared/async/useQuery'
import { useAsyncTask } from '@/shared/async/useAsyncTask'
import AppIcon from '@/shared/ui/icons/AppIcon.vue'
import { ElMessage } from 'element-plus'
import AgentModelSelect from './AgentModelSelect.vue'
import {
  groupAgentModels,
  readDefaultAgentModel,
  saveDefaultAgentModel,
} from '@/domain/agentModels'

const props = defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  changed: []
}>()

const activeTab = ref('context')
const query = useQuery((signal) => agentsApi.config(signal))
const action = useAsyncTask()
const toolsAction = useAsyncTask()
const draft = ref<AgentConfig>()
const defaultModel = ref('')
const preferenceError = ref('')
try {
  defaultModel.value = readDefaultAgentModel()
} catch {
  preferenceError.value = '无法读取浏览器中的默认模型设置'
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      draft.value = undefined
      void query.refresh()
    }
  },
)

watch(query.data, (value) => {
  if (value && !draft.value) draft.value = structuredClone(value.config)
})

const models = computed(() => query.data.value?.models ?? [])
const channels = computed(() => groupAgentModels(models.value).map((group) => group.channel))
const tools = computed(() => query.data.value?.tools ?? [])
const scheduler = computed(() => query.data.value?.scheduler ?? {})
const sandbox = computed(() => query.data.value?.sandbox)
const readonlyPaths = computed(() => query.data.value?.readonly_paths ?? [])

async function save() {
  if (!draft.value) return
  await action.run(async () => {
    if (defaultModel.value && !models.value.some((item) => item.reference === defaultModel.value)) {
      throw new Error('默认模型已不可用，请重新选择供应商渠道模型')
    }
    await agentsApi.updateConfig(draft.value!)
    try {
      saveDefaultAgentModel(defaultModel.value)
    } catch {
      throw new Error('服务端设置已保存，但浏览器默认模型保存失败，请检查浏览器存储权限后重试')
    }
    preferenceError.value = ''
    ElMessage.success('全局设置已更新，将在下一轮交互时生效')
    await query.refresh()
    emit('changed')
    emit('update:modelValue', false)
  })
}

async function toggleTool(plugin: string, enabled: boolean) {
  await toolsAction.run(async () => {
    await agentsApi.updateTool(plugin, enabled)
    ElMessage.success(`工具已${enabled ? '启用' : '禁用'}，将在下一轮生效`)
    await query.refresh()
    emit('changed')
  })
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="Agent 全局设置与运行环境"
    width="min(92vw, 760px)"
    class="agent-settings-dialog"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-alert
      v-if="query.error.value || action.error.value || toolsAction.error.value || preferenceError"
      :title="query.error.value || action.error.value || toolsAction.error.value || preferenceError"
      type="error"
      :closable="false"
    />
    <p v-if="query.pending.value" role="status">正在读取全局设置…</p>
    <el-button v-if="query.error.value" @click="query.refresh">重新读取设置</el-button>
    <div class="settings-intro">
      <div class="intro-icon">
        <AppIcon name="sliders" size="md" />
      </div>
      <div>
        <strong>全局 Agent 策略配置</strong>
        <p>
          这些参数由系统全局维护（模型默认值、上下文压缩预算、沙箱安全及工具插件），对话流中保持界面清爽，改动在下一轮次生效。
        </p>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="settings-tabs">
      <!-- 1. 上下文与压缩预算 -->
      <el-tab-pane label="上下文与压缩预算" name="context">
        <el-form v-if="draft" label-position="top" class="settings-form">
          <el-form-item label="默认供应商渠道 / 模型">
            <AgentModelSelect v-model="defaultModel" :models="models" label="默认模型" optional />
            <span class="field-hint">
              保存在当前浏览器，新建会话与 Workflow 续接自动选用；已有会话保留自己的模型。
            </span>
          </el-form-item>
          <div class="form-grid-2">
            <el-form-item label="用户上下文窗口 (Tokens)">
              <el-input-number
                v-model="draft.context_window"
                :min="1"
                :step="4096"
                class="w-full"
                placeholder="留空沿用模型最大容量"
              />
              <span class="field-hint">当前会话预算容量上限，超出后将触发自动压缩</span>
            </el-form-item>

            <el-form-item label="输出预留空间 (Tokens)">
              <el-input-number v-model="draft.output_tokens" :min="1" :step="512" class="w-full" />
              <span class="field-hint">每次生成响应为 Agent 保留的输出缓冲区</span>
            </el-form-item>
          </div>

          <div class="form-grid-2">
            <el-form-item label="自动压缩触发阈值 (Tokens)">
              <el-input-number
                v-model="draft.trigger_tokens"
                :min="1"
                :step="2048"
                class="w-full"
              />
              <span class="field-hint">达到此 Token 阈值时触发早期轮次归档总结</span>
            </el-form-item>

            <el-form-item label="压缩时保留近期 Tokens">
              <el-input-number v-model="draft.keep_tokens" :min="1" :step="1024" class="w-full" />
              <span class="field-hint">压缩时完整保留在会话尾部的近期活跃上下文</span>
            </el-form-item>
          </div>

          <div class="form-divider"><span>摘要模型定制</span></div>

          <div class="form-grid-2">
            <el-form-item label="摘要 AI 资源">
              <el-select
                v-model="draft.summary_ai"
                clearable
                :value-on-clear="null"
                placeholder="默认复用主模型"
                class="w-full"
              >
                <el-option v-for="ai in channels" :key="ai" :label="ai" :value="ai" />
              </el-select>
              <span class="field-hint">可配置轻量级模型降低上下文压缩开销</span>
            </el-form-item>

            <el-form-item label="摘要输出上限">
              <el-input-number
                v-model="draft.summary_max_tokens"
                :min="1"
                :step="256"
                class="w-full"
              />
              <span class="field-hint">压缩阶段生成记忆摘要的最大 Token 数</span>
            </el-form-item>
          </div>

          <el-form-item label="摘要提示模板 (Prompt Template)">
            <el-input
              v-model="draft.summary_prompt"
              type="textarea"
              :rows="3"
              placeholder="编写用于指导压缩时提取关键诊断结论的系统提示词"
            />
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <!-- 2. 工具插件与调度 -->
      <el-tab-pane label="工具插件与调度" name="tools">
        <div class="scheduler-card">
          <div class="scheduler-stat">
            <span class="stat-label">并发只读读锁</span>
            <strong class="stat-value">
              {{ scheduler.reading ?? '未知' }} / {{ scheduler.read_concurrency ?? '未知' }}
            </strong>
          </div>
          <div class="scheduler-stat">
            <span class="stat-label">排他写锁占用</span>
            <strong class="stat-value">{{ scheduler.writing ?? '未知' }} / 1</strong>
          </div>
          <div class="scheduler-stat">
            <span class="stat-label">排队等待中</span>
            <strong class="stat-value">{{ scheduler.queued ?? '未知' }} 项</strong>
          </div>
        </div>

        <div class="tools-list">
          <div
            v-for="tool in tools"
            :key="tool.plugin + tool.name"
            class="tool-item"
            :class="{ disabled: !tool.enabled }"
          >
            <div class="tool-main">
              <div class="tool-header">
                <span class="tool-name">
                  <AppIcon name="terminal" size="sm" />
                  <strong>{{ tool.name }}</strong>
                </span>
                <span class="tool-badge" :class="tool.execution ?? ''">
                  {{
                    tool.execution === 'exclusive'
                      ? '工作区独占写'
                      : tool.execution === 'read'
                        ? '并发只读'
                        : '按调用动作确定'
                  }}
                </span>
                <span class="tool-tokens">约 {{ tool.definition_tokens }} Tokens</span>
              </div>
              <p class="tool-desc">{{ tool.description }}</p>
              <small>插件 {{ tool.plugin }} · 代次 {{ tool.generation ?? '未注册' }}</small>
              <details v-if="tool.input_schema">
                <summary>查看工具 Schema</summary>
                <pre>{{ JSON.stringify(tool.input_schema, null, 2) }}</pre>
              </details>
            </div>
            <div class="tool-switch">
              <el-switch
                :model-value="tool.enabled"
                :disabled="toolsAction.pending.value"
                @change="(val: string | number | boolean) => toggleTool(tool.plugin, Boolean(val))"
              />
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- 3. 沙箱隔离与安全 -->
      <el-tab-pane label="沙箱与安全隔离" name="sandbox">
        <div
          v-if="sandbox"
          class="sandbox-status-card"
          :class="{ secure: sandbox.enabled && sandbox.available }"
        >
          <div class="status-icon">
            <AppIcon name="shield" size="md" />
          </div>
          <div>
            <strong>
              {{
                !sandbox?.enabled
                  ? '沙箱未开启（使用服务进程权限运行）'
                  : sandbox?.available
                    ? '沙箱就绪（Bubblewrap 轻量级容器隔离）'
                    : '沙箱环境不可用：宿主未检测到 bubblewrap'
              }}
            </strong>
            <p>沙箱配置控制 Shell 子进程的隔离与网络访问，工作区文件权限由服务端执行。</p>
          </div>
        </div>

        <el-form v-if="draft" label-position="top" class="mt-4">
          <div class="form-grid-2">
            <el-form-item label="启用沙箱隔离执行">
              <el-switch v-model="draft.sandbox.enabled" />
            </el-form-item>
            <el-form-item label="允许沙箱网络外联">
              <el-switch v-model="draft.sandbox.network" />
            </el-form-item>
          </div>

          <div class="readonly-section">
            <span class="label">当前只读受保护路径：</span>
            <div class="path-tags">
              <el-tag v-for="p in readonlyPaths" :key="p" type="info" size="small">
                {{ p }}
              </el-tag>
            </div>
          </div>
        </el-form>
      </el-tab-pane>

      <!-- 4. 基础运行参数 -->
      <el-tab-pane label="基础设置" name="general">
        <el-form v-if="draft" label-position="top">
          <div class="form-grid-2">
            <el-form-item label="Memory 时区 (IANA)">
              <el-input v-model="draft.timezone" placeholder="Asia/Shanghai" />
              <span class="field-hint">用于每日记忆提取与日程计算</span>
            </el-form-item>

            <el-form-item label="只读工具最大并发数">
              <el-input-number v-model="draft.read_concurrency" :min="1" class="w-full" />
              <span class="field-hint">限制多工具并行读取任务的峰值线程</span>
            </el-form-item>
            <el-form-item label="模型无活动超时（秒）">
              <el-input-number v-model="draft.idle_timeout" :min="1" />
            </el-form-item>
            <el-form-item label="摘要上下文容量（可选）">
              <el-input-number v-model="draft.summary_context_window" :min="1" />
            </el-form-item>
          </div>
        </el-form>
      </el-tab-pane>
    </el-tabs>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="emit('update:modelValue', false)">取消</el-button>
        <el-button
          type="primary"
          :disabled="!draft || query.pending.value"
          :loading="action.pending.value"
          @click="save"
        >
          保存全局设置
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.settings-intro {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 12px 16px;
  margin-bottom: 16px;
  background: color-mix(in srgb, var(--el-color-primary) 8%, var(--surface));
  border: 1px solid color-mix(in srgb, var(--el-color-primary) 20%, transparent);
  border-radius: 8px;
}

.intro-icon {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--el-color-primary) 15%, transparent);
  color: var(--el-color-primary);
  flex-shrink: 0;
}

.settings-intro strong {
  display: block;
  font-size: 13px;
  color: var(--el-text-color-primary);
}

.settings-intro p {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}

.form-grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.field-hint {
  display: block;
  margin-top: 4px;
  font-size: 11px;
  color: var(--muted);
}

.form-divider {
  display: flex;
  align-items: center;
  margin: 16px 0 12px;
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
}

.form-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border);
  margin-left: 12px;
}

.scheduler-card {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  padding: 14px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 16px;
}

.scheduler-stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-label {
  font-size: 11px;
  color: var(--muted);
}

.stat-value {
  font-size: 15px;
  color: var(--el-text-color-primary);
  font-family: ui-monospace, monospace;
}

.tools-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 360px;
  overflow-y: auto;
}

.tool-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  transition: all 0.15s ease;
}

.tool-item:hover {
  border-color: color-mix(in srgb, var(--el-color-primary) 30%, transparent);
}

.tool-item.disabled {
  opacity: 0.6;
  background: var(--el-fill-color-light);
}

.tool-main {
  flex: 1;
  min-width: 0;
}

.tool-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tool-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--el-text-color-primary);
}

.tool-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
}

.tool-badge.read {
  background: #dbeafe;
  color: #1d4ed8;
}

.tool-badge.exclusive {
  background: #fef3c7;
  color: #b45309;
}

.tool-tokens {
  font-size: 11px;
  color: var(--muted);
  font-family: ui-monospace, monospace;
}

.tool-desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--muted);
}

.sandbox-status-card {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 14px 16px;
  border-radius: 8px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #991b1b;
}

.sandbox-status-card.secure {
  background: #f0fdf4;
  border-color: #bbf7d0;
  color: #166534;
}

.status-icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.6);
  flex-shrink: 0;
}

.sandbox-status-card strong {
  display: block;
  font-size: 13px;
}

.sandbox-status-card p {
  margin: 2px 0 0;
  font-size: 12px;
  opacity: 0.85;
}

.readonly-section {
  margin-top: 12px;
}

.readonly-section .label {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 6px;
}

.path-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

:global(.dark) .sandbox-status-card {
  background: #450a0a;
  border-color: #7f1d1d;
  color: #fca5a5;
}

:global(.dark) .sandbox-status-card.secure {
  background: #052e16;
  border-color: #14532d;
  color: #86efac;
}

:global(.dark) .tool-badge.read {
  background: #1e3a8a;
  color: #93c5fd;
}

:global(.dark) .tool-badge.exclusive {
  background: #78350f;
  color: #fde68a;
}
</style>
