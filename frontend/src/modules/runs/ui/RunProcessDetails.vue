<script setup lang="ts">
import { stages } from '@/modules/workflows/model/public'
import type { useRunDetail } from '../composables/useRunDetail'
import PhaseReport from './PhaseReport.vue'
defineProps<{
  phases: ReturnType<typeof useRunDetail>['phases']
  active: boolean
  advanced: boolean
}>()
</script>
<template>
  <details
    v-for="stage in stages.filter((item) =>
      ['collect', 'analyze', 'notify', 'finish'].includes(item.key),
    )"
    :key="stage.key"
    class="border-b last:border-0"
  >
    <summary class="report-disclosure font-medium">
      {{ stage.key === 'notify' ? '通知状态' : stage.label }}
    </summary>
    <PhaseReport class="pb-3" :report="phases[stage.key]" :active="active" :advanced="advanced" />
  </details>
</template>
