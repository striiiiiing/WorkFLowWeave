<script setup lang="ts">
import { computed } from 'vue'
import type { ChannelConfig } from '@/modules/resources/public'
import type { JsonObject } from '@/shared/types'
import type { WorkflowEditorController } from '../composables/useWorkflowEditor'
import { optionSchema } from '@/shared/schema/capabilities'
import ParameterField from '@/shared/schema/ParameterField.vue'
import SectionCard from '@/shared/ui/SectionCard.vue'
type WorkflowCapability = {
  kind: 'channel' | 'collector' | 'tool'
  name: string
  options_schema: JsonObject
}
const props = defineProps<{
  editor: WorkflowEditorController
  channels: readonly ChannelConfig[]
  capabilities: readonly WorkflowCapability[]
  advanced?: boolean
}>()
const emit = defineEmits<{ add: []; edit: [channel: ChannelConfig] }>()
const draft = () => props.editor.draft.value!
const capabilityByChannel = computed(() =>
  Object.fromEntries(
    props.channels.map((channel) => [
      channel.id,
      props.capabilities.find((item) => item.kind === 'channel' && item.name === channel.channel),
    ]),
  ),
)
function channel(id: string) {
  return props.channels.find((item) => item.id === id)
}
</script>
<template>
  <SectionCard title="4. 渠道分发" description="选择结果通知的目标渠道">
    <template #actions>
      <el-button size="small" @click="emit('add')">添加渠道</el-button>
    </template>
    <el-form-item label="通知渠道">
      <el-select
        :model-value="draft().channels"
        multiple
        filterable
        @update:model-value="editor.setChannels($event)"
      >
        <el-option
          v-for="item in channels"
          :key="item.id"
          :value="item.id"
          :label="`${item.id}${item.enabled ? '' : '（已停用）'}`"
          :disabled="!item.enabled && !draft().channels.includes(item.id)"
        />
      </el-select>
    </el-form-item>
    <p class="resource-hint muted text-sm mb-4">
      渠道来自资源配置中心并可在多个工作流复用；此处只保存渠道引用，工作流参数覆盖需要单独启用。
    </p>
    <el-alert
      v-if="!draft().channels.length"
      title="尚未选择通知渠道，运行结果不会发送通知。"
      type="info"
      :closable="false"
      class="mb-4"
    />
    <div
      v-for="(channelId, index) in draft().channels"
      :key="channelId"
      class="channel-binding-card"
      :aria-label="`通知渠道 ${channelId}`"
    >
      <div class="channel-binding-heading">
        <div class="flex items-center gap-3 min-w-0 flex-wrap">
          <span class="channel-index">{{ index + 1 }}</span>
          <div class="min-w-0">
            <h3 class="font-semibold mono break-all">
              {{ channelId }}
            </h3>
            <p v-if="channel(channelId)" class="muted text-sm mt-1">
              {{ channel(channelId)?.channel }}
            </p>
          </div>
          <el-tag
            v-if="channel(channelId)"
            :type="channel(channelId)?.enabled === false ? 'warning' : 'success'"
            effect="plain"
          >
            {{ channel(channelId)?.enabled === false ? '已停用' : '已启用' }}
          </el-tag>
        </div>
      </div>
      <el-alert
        v-if="channel(channelId)?.enabled === false"
        title="此渠道已停用，本次运行不会发送；重新启用后会恢复原设置。"
        type="warning"
        :closable="false"
        class="mb-3"
      />
      <el-form-item :label="`${channelId}：覆盖本次发送参数`">
        <el-switch
          :model-value="!!draft().channel_overrides[channelId]"
          @update:model-value="editor.toggleChannelOverride(channelId, Boolean($event))"
        />
      </el-form-item>
      <ParameterField
        v-if="draft().channel_overrides[channelId]"
        :model-value="draft().channel_overrides[channelId].options"
        :prop="`channel_overrides.${channelId}.options`"
        label="本次发送参数"
        :schema="optionSchema(capabilityByChannel[channelId]?.options_schema, 'workflow')"
        @update:model-value="editor.updateChannelOptions(channelId, $event)"
      />
      <div class="channel-binding-footer">
        <p class="muted text-xs">
          复用资源配置；仅在此工作流中覆盖本次发送参数。编辑会更新资源中心中的共享渠道。
        </p>
        <el-button
          v-if="channel(channelId)"
          size="small"
          @click="emit('edit', channel(channelId)!)"
        >
          编辑
        </el-button>
      </div>
    </div>
    <el-form-item v-if="advanced" label="允许发送部分成功的结果">
      <el-switch
        :model-value="draft().send_partial"
        @update:model-value="editor.update({ send_partial: Boolean($event) })"
      />
    </el-form-item>
  </SectionCard>
</template>
<style scoped>
.channel-binding-card {
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 16px;
}
.channel-binding-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
}
.channel-index {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border-radius: 6px;
  padding: 3px 9px;
  font-weight: 700;
}
.channel-binding-footer {
  border-top: 1px solid var(--el-border-color-lighter);
  margin-top: 16px;
  padding-top: 14px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
</style>
