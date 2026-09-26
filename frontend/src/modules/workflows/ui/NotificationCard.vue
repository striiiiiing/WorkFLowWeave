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
    <template #actions><el-button size="small" @click="emit('add')">添加渠道</el-button></template>
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
    <div v-for="channelId in draft().channels" :key="channelId" class="border rounded-lg p-4 mb-4">
      <div class="flex items-center gap-2 mb-3">
        <span class="mono break-all">
          {{ channelId }}{{ channel(channelId)?.enabled === false ? '（已停用）' : '' }}
        </span>
        <el-button
          v-if="channel(channelId)"
          text
          size="small"
          @click="emit('edit', channel(channelId)!)"
        >
          编辑共用渠道
        </el-button>
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
    </div>
    <el-form-item v-if="advanced" label="允许发送部分成功的结果">
      <el-switch
        :model-value="draft().send_partial"
        @update:model-value="editor.update({ send_partial: Boolean($event) })"
      />
    </el-form-item>
  </SectionCard>
</template>
