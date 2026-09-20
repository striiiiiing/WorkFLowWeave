<script setup lang="ts">
import type { WorkflowDefinition, ChannelConfig } from '@/types'
import SectionCard from '@/components/common/SectionCard.vue'
const model = defineModel<WorkflowDefinition>({ required: true })
defineProps<{ channels: ChannelConfig[]; advanced?: boolean }>()
function selectChannels(ids: string[]) {
  model.value = {
    ...model.value,
    channels: ids,
    channel_overrides: Object.fromEntries(
      Object.entries(model.value.channel_overrides).filter(([id]) => ids.includes(id)),
    ),
  }
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
          :label="channel.id"
        />
      </el-select>
    </el-form-item>
    <el-form-item v-if="advanced" label="允许发送部分成功的结果">
      <el-switch v-model="model.send_partial" />
    </el-form-item>
  </SectionCard>
</template>
