<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, type FormInstance } from 'element-plus'
import type { ChannelConfig } from '../model/public'
import type { SchemaCapability } from '@/shared/schema/types'
import type { JsonObject } from '@/shared/types'
import { useChannelEditor } from '../composables/useChannelEditor'
import { idRule } from '../model/source/forms'
import ParameterField from '@/shared/schema/ParameterField.vue'
import ChannelConversation from './ChannelConversation.vue'
import WechatLogin from './WechatLogin.vue'
const props = defineProps<{ initial?: ChannelConfig; capabilities: readonly SchemaCapability[] }>()
const emit = defineEmits<{
  saved: [value: ChannelConfig]
  persisted: [value: ChannelConfig]
  cancel: []
}>()
const {
  draft,
  updateChannel,
  updateEnabled,
  updateAgentEnabled,
  updateOptions,
  updateAdvanced,
  save,
  capabilities,
  capabilityName,
  capability,
  optionParameterSchema,
  updateId,
  submit: saveDraft,
  startConnection,
  connection,
  connectionPending,
  connectionError,
  requiresFirstMessage,
  needsReconnect,
  finishRequired,
  connectionReady,
  isPersisted,
  cancelConnection,
  finishConnection,
} = useChannelEditor(props)
const form = ref<FormInstance>()
const visibleOptionsSchema = computed(() => {
  if (capabilityName.value !== 'wechat_openclaw') return optionParameterSchema.value
  const schema = (optionParameterSchema.value ?? { type: 'object', properties: {} }) as JsonObject
  const properties = { ...((schema.properties ?? {}) as JsonObject) }
  delete properties.account_id
  return {
    ...schema,
    properties,
    required: ((schema.required as string[] | undefined) ?? []).filter(
      (name) => name !== 'account_id',
    ),
  } as JsonObject
})
async function submit(forceReconnect = false) {
  const result = await saveDraft(async () => (await form.value?.validate(() => {})) ?? false)
  if (result.status !== 'success') return
  emit('persisted', result.value)
  if (requiresFirstMessage.value && result.value.enabled) {
    if (
      forceReconnect ||
      needsReconnect.value ||
      connection.value?.state !== 'connected' ||
      !connectionReady.value
    ) {
      const retry =
        forceReconnect ||
        needsReconnect.value ||
        connection.value?.state === 'failed' ||
        connection.value?.state === 'cancelled' ||
        !connectionReady.value ||
        !!connectionError.value
      await startConnection(result.value.id, retry)
      return
    }
  }
  ElMessage.success('资源已保存')
  emit('saved', result.value)
}
async function finish() {
  const connected = await finishConnection()
  if (!connected) return
  ElMessage.success('成功连接')
  emit('saved', connected)
}
</script>
<template>
  <el-alert
    v-if="save.error.value"
    :title="save.error.value"
    type="error"
    :closable="false"
    show-icon
  />
  <el-form
    ref="form"
    novalidate
    :model="draft"
    :disabled="save.pending.value"
    label-position="top"
    @submit.prevent.stop="submit()"
  >
    <el-form-item label="资源编号" prop="id" :rules="{ ...idRule, required: false }">
      <el-input
        :model-value="draft.id"
        :disabled="!!initial || isPersisted"
        placeholder="可自行填写；留空则自动生成"
        @update:model-value="updateId"
      />
    </el-form-item>
    <p v-if="capability" class="muted mb-4">{{ capability.description }}</p>
    <el-alert
      v-if="capabilityName && !capability"
      title="当前插件未注册，请检查插件加载状态或选择已注册能力。"
      type="error"
      :closable="false"
    />
    <el-form-item label="渠道能力名称" prop="channel" :rules="idRule">
      <el-select
        :model-value="draft.channel"
        @update:model-value="updateChannel"
        filterable
        placeholder="选择渠道"
      >
        <el-option
          v-for="item in capabilities"
          :key="item.name"
          :value="item.name"
          :label="item.name"
        />
        <el-option
          v-if="draft.channel && !capability"
          :value="draft.channel"
          :label="draft.channel + '（未注册）'"
          disabled
        />
      </el-select>
    </el-form-item>
    <el-form-item label="启用渠道">
      <el-switch
        :model-value="draft.enabled"
        @update:model-value="updateEnabled(Boolean($event))"
      />
    </el-form-item>
    <section v-if="requiresFirstMessage && draft.enabled" class="mb-4" aria-label="首次连接">
      <el-alert
        v-if="connection?.state === 'connected' && connectionReady"
        title="成功连接"
        type="success"
        :closable="false"
        show-icon
      />
      <el-alert
        v-else-if="connection?.state === 'connected' && connectionError"
        :title="connectionError"
        type="error"
        :closable="false"
        show-icon
      />
      <el-alert
        v-else-if="connection?.state === 'waiting_message'"
        title="等待首条私聊消息"
        description="请在渠道开启期间，向机器人发送第一条私聊消息。收到后，机器人会回复“成功连接”。"
        type="info"
        :closable="false"
        show-icon
      />
      <el-alert
        v-else-if="(connection?.state === 'connecting' || connectionPending) && !connectionError"
        title="正在连接渠道"
        description="请保持此窗口开启，并向机器人发送第一条私聊消息。"
        type="info"
        :closable="false"
        show-icon
      />
      <el-alert
        v-else-if="
          connection?.state === 'failed' || connection?.state === 'cancelled' || connectionError
        "
        :title="
          connection?.error?.message ||
          connectionError ||
          connection?.message ||
          '连接未完成，请重试。'
        "
        type="error"
        :closable="false"
        show-icon
      />
      <el-alert
        v-else
        title="首次连接需要一条私聊消息"
        description="保存并连接后，请在渠道开启期间向机器人发送第一条私聊消息。"
        type="info"
        :closable="false"
        show-icon
      />
      <el-button
        v-if="
          connectionPending ||
          connection?.state === 'waiting_message' ||
          connection?.state === 'connecting'
        "
        class="mt-3"
        :disabled="save.pending.value"
        @click="cancelConnection('已取消首次连接。')"
      >
        取消连接
      </el-button>
      <el-button
        v-else-if="connection?.state === 'connected' && connectionReady"
        class="mt-3"
        :disabled="save.pending.value"
        @click="submit(true)"
      >
        重新连接
      </el-button>
      <el-button
        v-if="finishRequired && connectionReady"
        class="mt-3"
        type="primary"
        @click="finish"
      >
        完成
      </el-button>
    </section>
    <el-form-item v-if="capability?.capabilities.includes('conversation')" label="接入 Agent 对话">
      <el-switch
        :model-value="draft.agent_enabled"
        @update:model-value="updateAgentEnabled(Boolean($event))"
      />
    </el-form-item>
    <ChannelConversation
      v-if="
        initial &&
        draft.channel === initial.channel &&
        capability?.capabilities.includes('conversation')
      "
      :key="initial.id"
      :channel-id="initial.id"
    />
    <p v-else-if="capability?.capabilities.includes('conversation')" class="muted mb-4">
      保存渠道后，可在编辑时绑定已有 Agent 对话。
    </p>
    <WechatLogin
      v-if="capabilityName === 'wechat_openclaw' && capability"
      :options="draft.options"
      @update="updateOptions"
    />
    <ParameterField
      v-if="capabilityName"
      :key="`options-${capabilityName}`"
      :model-value="draft.options"
      @update:model-value="updateOptions"
      prop="options"
      label="插件参数 (options)"
      :schema="visibleOptionsSchema"
      :excluded-properties="capabilityName === 'wechat_openclaw' ? ['account_id'] : undefined"
    />
    <details class="advanced-fields">
      <summary class="report-disclosure">高级配置</summary>
      <el-form-item label="超时 / 秒">
        <el-input-number
          :model-value="draft.timeout"
          @update:model-value="updateAdvanced({ timeout: $event })"
          :min="0.001"
        />
      </el-form-item>
    </details>
    <div class="flex justify-end gap-3">
      <el-button @click="emit('cancel')">取消</el-button>
      <el-button
        v-if="!(finishRequired && connectionReady)"
        type="primary"
        native-type="submit"
        :loading="save.pending.value || connectionPending"
        :disabled="connectionPending"
      >
        {{
          requiresFirstMessage && draft.enabled
            ? connection?.state === 'connected' && !needsReconnect
              ? '保存资源'
              : ['failed', 'cancelled'].includes(connection?.state ?? '') || needsReconnect
                ? '重新连接'
                : '保存并连接'
            : '保存资源'
        }}
      </el-button>
    </div>
  </el-form>
</template>
