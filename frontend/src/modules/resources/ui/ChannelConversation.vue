<script setup lang="ts">
import { useChannelConversation } from '../composables/useChannelConversation'

const props = defineProps<{ channelId: string }>()
const { binding, selected, options, query, action, save } = useChannelConversation(
  () => props.channelId,
)
</script>

<template>
  <el-form-item label="绑定 Agent 对话">
    <div class="w-full">
      <el-alert
        v-if="query.error.value || action.error.value"
        :title="query.error.value || action.error.value"
        type="error"
        :closable="false"
      />
      <p v-if="binding" class="muted mb-2">当前：{{ binding.session_id ?? '未绑定' }}</p>
      <el-select
        v-model="selected"
        aria-label="选择绑定对话"
        filterable
        clearable
        placeholder="选择已有对话"
        :loading="query.pending.value"
        :disabled="!binding || action.pending.value"
      >
        <el-option
          v-for="item in options"
          :key="item.session_id"
          :value="item.session_id"
          :label="`${item.title || item.session_id} / ${item.session_id}`"
        />
        <el-option
          v-if="
            binding?.session_id && !options.some((item) => item.session_id === binding?.session_id)
          "
          :value="binding.session_id"
          :label="binding.session_id"
        />
      </el-select>
      <div class="flex flex-wrap items-center gap-2 mt-3">
        <el-button
          :loading="action.pending.value"
          :disabled="!binding || query.pending.value || (selected || null) === binding.session_id"
          @click="save()"
        >
          保存绑定
        </el-button>
        <el-button
          :disabled="!binding?.session_id || query.pending.value || action.pending.value"
          @click="save(null)"
        >
          解绑
        </el-button>
        <router-link
          v-if="binding?.session_id"
          :to="`/agents/${encodeURIComponent(binding.session_id)}`"
        >
          打开对话
        </router-link>
        <el-button
          :loading="query.pending.value"
          :disabled="action.pending.value"
          @click="query.refresh"
        >
          刷新
        </el-button>
      </div>
      <p class="muted text-sm mt-2">同一实例的入站消息共用此对话，也可通过 Web 查看和调试。</p>
    </div>
  </el-form-item>
</template>
