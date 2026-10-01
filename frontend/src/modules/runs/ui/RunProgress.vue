<script setup lang="ts">
import { computed } from 'vue'
import type { SessionRecord } from '../model/types'
import {
  progressIdentity,
  progressItemLabel,
  progressStages,
  progressStatusLabel,
  progressTagType,
} from '../model/progress'
import { availabilityLabels, stages } from '../model/session'
import AppIcon from '@/shared/ui/icons/AppIcon.vue'

const props = defineProps<{ session: SessionRecord; active: boolean }>()
const groups = computed(() =>
  progressStages.map((key) => ({
    key,
    title: stages.find((stage) => stage.key === key)!.label,
    items: props.session.progress
      .filter((item) => item.stage === key && item.event !== 'lifecycle')
      .sort((left, right) => left.order - right.order ||
        progressIdentity(left).localeCompare(progressIdentity(right))),
  })),
)
</script>
<template>
  <div class="run-progress" aria-label="执行进度">
    <section
      v-for="group in groups"
      :key="group.key"
      class="progress-stage"
      :aria-label="group.title"
    >
      <div class="stage-heading">
        <h3>{{ group.title }}</h3>
        <span v-if="active && session.stage === group.key" class="stage-current">
          <AppIcon name="activity" size="sm" />
          当前阶段
        </span>
      </div>
      <p v-if="!group.items.length" class="muted text-sm">
        {{ group.key === 'notify' ? '没有通知投递项。' : '没有此阶段的执行项。' }}
      </p>
      <ul v-else class="progress-items">
        <li
          v-for="item in group.items"
          :key="progressIdentity(item)"
          class="progress-item"
          :data-progress-key="progressIdentity(item)"
        >
          <div class="item-heading">
            <div class="item-name">
              <span>{{ progressItemLabel(item) }}</span>
              <span v-if="item.event === 'delivery'" class="muted text-xs">
                {{ item.output_id === 'final' ? '最终报告' : item.output_id }}
              </span>
            </div>
            <el-tag :type="progressTagType(item)" size="small">
              {{ progressStatusLabel(item) }}
            </el-tag>
          </div>
          <p v-if="item.error" class="item-error text-sm" role="alert">{{ item.error.message }}</p>
          <p v-if="item.event === 'aggregate' && item.status === 'success'" class="muted text-sm">
            {{ item.summary.fan_in === true ? '业务汇总已完成。' : '输出已整理完成。' }}
            {{
              item.summary.outputs_available === false
                ? '本次没有可发送的输出。'
                : `最终报告${availabilityLabels[item.availability]}。`
            }}
            <span v-if="active">通知与收尾尚未结束。</span>
          </p>
          <p v-else-if="item.result_ref && item.availability !== 'available'" class="muted text-xs">
            正文{{ availabilityLabels[item.availability] }}
          </p>
        </li>
      </ul>
    </section>
  </div>
</template>
<style scoped>
.progress-stage {
  padding: 16px 0;
  border-top: 1px solid var(--el-border-color-lighter);
}
.progress-stage:first-child {
  padding-top: 0;
  border-top: 0;
}
.stage-heading,
.item-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.stage-heading {
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.stage-heading h3 {
  font-size: 14px;
  font-weight: 600;
}
.stage-current {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--el-color-primary);
  font-size: 12px;
}
.progress-items {
  display: grid;
  gap: 8px;
}
.progress-item {
  padding: 10px 0;
  min-width: 0;
}
.item-heading {
  align-items: flex-start;
}
.item-heading :deep(.el-tag) {
  flex-shrink: 0;
}
.item-name {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 5px 10px;
  min-width: 0;
  overflow-wrap: anywhere;
}
.progress-item p {
  margin-top: 6px;
  overflow-wrap: anywhere;
}
.item-error {
  color: var(--el-color-danger);
}
</style>
