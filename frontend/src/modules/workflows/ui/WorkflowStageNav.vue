<script setup lang="ts">
import AppIcon from '@/shared/ui/icons/AppIcon.vue'

export interface WorkflowStageNavItem {
  id: string
  title: string
  detail: string
}

defineProps<{
  activeStage: string
  stages: readonly WorkflowStageNavItem[]
}>()
const emit = defineEmits<{ select: [stage: string] }>()
</script>

<template>
  <nav class="pipeline-step-nav" aria-label="工作流阶段">
    <button
      v-for="(stage, index) in stages"
      :key="stage.id"
      type="button"
      class="step-nav-btn"
      :class="{ active: activeStage === stage.id }"
      :aria-pressed="activeStage === stage.id"
      @click="emit('select', stage.id)"
    >
      <span class="step-num">{{ index + 1 }}</span>
      <span class="step-text">
        <strong>{{ stage.title }}</strong>
        <small>{{ stage.detail }}</small>
      </span>
    </button>
    <button
      type="button"
      class="step-nav-btn overview-btn"
      :class="{ active: activeStage === 'all' }"
      :aria-pressed="activeStage === 'all'"
      @click="emit('select', 'all')"
    >
      <AppIcon name="workflow" size="sm" />
      <span>全览模式</span>
    </button>
  </nav>
</template>

<style scoped>
.pipeline-step-nav {
  display: flex;
  flex-wrap: wrap;
  padding: 12px;
  gap: 8px;
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  background: var(--el-bg-color);
  margin-bottom: 20px;
}
.step-nav-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  padding: 12px;
  border-radius: 8px;
  min-height: 48px;
  text-align: left;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}
.step-nav-btn.active {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}
.step-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
}
.step-text small {
  font-size: 11px;
}
.step-num {
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border: 1px solid currentColor;
  border-radius: 50%;
  font-size: 12px;
}
.overview-btn {
  justify-content: center;
  flex: 0 1 auto;
  font-size: 12px;
}
@media (max-width: 640px) {
  .step-nav-btn {
    flex-basis: 40%;
    padding: 8px;
  }
  .overview-btn {
    flex-basis: 100%;
  }
}
</style>
