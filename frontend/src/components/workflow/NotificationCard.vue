<script setup lang="ts">
import { computed } from 'vue'
import type { WorkflowDefinition, ChannelConfig } from '@/types'
import { optionSchema } from '@/shared/schema/capabilities'
import { systemApi } from '@/api/system'
import { useQuery } from '@/shared/async/useQuery'
import ParameterField from '@/shared/schema/ParameterField.vue'
import SectionCard from '@/shared/ui/SectionCard.vue'
const model = defineModel<WorkflowDefinition>({ required: true })
const props = defineProps<{ channels: ChannelConfig[]; advanced?: boolean }>()
const {
  data: plugins,
  error: pluginError,
  refresh,
} = useQuery((signal) => systemApi.plugins(signal))
const channelCapabilities = computed(() =>
  Object.fromEntries(
    props.channels.map((channel) => [
      channel.id,
      plugins.value?.find((item) => item.kind === 'channel' && item.name === channel.channel),
    ]),
  ),
)
function selectChannels(ids: string[]) {
  model.value = {
    ...model.value,
    channels: ids,
    channel_overrides: Object.fromEntries(
      Object.entries(model.value.channel_overrides).filter(([id]) => ids.includes(id)),
    ),
  }
}
function channelById(id: string) {
  return props.channels.find((channel) => channel.id === id)
}
function toggleOverride(id: string, enabled: boolean) {
  const overrides = { ...model.value.channel_overrides }
  if (enabled) overrides[id] = { options: {} }
  else delete overrides[id]
  model.value = { ...model.value, channel_overrides: overrides }
}
</script>
<template>
  <SectionCard title="4. 渠道分发" description="选择结果通知的目标渠道">
    <el-form-item label="通知渠道">
      <el-select
        :model-value="model.channels"
        multiple
        filterable
        @update:model-value="selectChannels"
      >
        <el-option
          v-for="channel in channels"
          :key="channel.id"
          :value="channel.id"
          :label="`${channel.id}${channel.enabled ? '' : '（已停用）'}`"
          :disabled="!channel.enabled && !model.channels.includes(channel.id)"
        />
      </el-select>
    </el-form-item>
    <el-alert v-if="pluginError" :title="pluginError" type="error" :closable="false" />
    <el-button v-if="pluginError" @click="refresh">重新加载渠道选项</el-button>
    <div v-for="channelId in model.channels" :key="channelId" class="border rounded-lg p-4 mb-4">
      <div class="flex items-center gap-2 mb-3">
        <span class="mono break-all">
          {{ channelId }}{{ channelById(channelId)?.enabled === false ? '（已停用）' : '' }}
        </span>
      </div>
      <el-alert
        v-if="channelById(channelId)?.enabled === false"
        title="此渠道已停用，本次运行不会发送；重新启用后会恢复原设置。"
        type="warning"
        :closable="false"
        class="mb-3"
      />
      <el-form-item :label="`${channelId}：自定义本次发送`">
        <el-switch
          :model-value="!!model.channel_overrides[channelId]"
          @update:model-value="toggleOverride(channelId, Boolean($event))"
        />
      </el-form-item>
      <template v-if="model.channel_overrides[channelId]">
        <p class="muted text-sm mb-3">仅覆盖本工作流；未填写的字段沿用通知渠道。</p>
        <ParameterField
          v-model="model.channel_overrides[channelId].options"
          :prop="`channel_overrides.${channelId}.options`"
          label="本次发送参数"
          :schema="optionSchema(channelCapabilities[channelId]?.options_schema, 'workflow')"
        />
      </template>
    </div>
    <el-form-item v-if="advanced" label="允许发送部分成功的结果">
      <el-switch v-model="model.send_partial" />
    </el-form-item>
  </SectionCard>
</template>
