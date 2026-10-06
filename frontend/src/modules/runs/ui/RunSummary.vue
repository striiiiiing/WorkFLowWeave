<script setup lang="ts">
import { computed } from 'vue'
import type { SessionRecord } from '@/modules/workflows/model/public'
import { stages, formatTime } from '@/modules/workflows/model/public'
import StatusBadge from './StatusBadge.vue'
const props = defineProps<{ session: SessionRecord }>()
const stageName = computed(
  () => stages.find((stage) => stage.key === props.session.stage)?.label ?? '尚未开始',
)
</script>
<template>
  <div class="grid grid-cols-2 lg:grid-cols-4 gap-5 text-sm">
    <div>
      <p class="muted mb-2">运行状态</p>
      <StatusBadge :status="session.status" />
    </div>
    <div>
      <p class="muted mb-2">当前阶段</p>
      {{ stageName }}
    </div>
    <div>
      <p class="muted mb-2">开始时间</p>
      {{ formatTime(session.created_at) }}
    </div>
    <div>
      <p class="muted mb-2">结束时间</p>
      {{ session.finished_at ? formatTime(session.finished_at) : '尚未结束' }}
    </div>
  </div>
  <el-alert
    v-if="session.error"
    :title="session.error.message"
    type="error"
    :closable="false"
    class="mt-5"
  />
</template>
